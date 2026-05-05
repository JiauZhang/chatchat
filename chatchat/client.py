import os, httpx, types
from pathlib import Path
from conippets import json
from importlib import import_module
from chatchat.providers import __providers__

__secret_file__ = os.environ.get('CHATCHAT_SECRET_FILE', str(Path.home() / '.chatchat.json'))

class BaseClient:
    def __init__(self, provider, base_url, model=None, instruction=None, http_options={}):
        self.provider = provider
        self.instruction = instruction
        if not os.path.exists(__secret_file__):
            json.write(__secret_file__, {})
        secret_data = json.read(__secret_file__)
        self.verify_secret_data(secret_data, self.provider)
        self.secret_file = __secret_file__
        self.secret_data = secret_data[self.provider]
        self.api_key = self.secret_data['api_key']
        self.model = model
        self.client = httpx.Client(
            base_url=base_url, **http_options, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )
        self.base_url = self.client.base_url
        self.headers = self.client.headers
        self.history = [] if instruction is None else [self.system_message()]

        self._role_key = 'role'
        self._reasoning_content_key = 'reasoning_content'
        self._content_key = 'content'
        self._tool_calls_key = 'tool_calls'
        self._tool_call_index_key = 'index'
        self._tool_call_id_key = 'id'

    def system_message(self):
        return {'role': 'system', 'content': self.instruction}

    def set_instruction(self, instruction):
        is_none = self.instruction is None
        self.instruction = instruction
        system_message = self.system_message()
        if is_none:
            self.history = [system_message] + self.history
        else:
            self.history[0] = system_message

    def verify_secret_data(self, secret_data, provider):
        has_provider = provider in secret_data
        has_key = False
        if has_provider:
            provider_data = secret_data[provider]
            has_key = 'api_key' in provider_data
        if not (has_provider and has_key):
            print('You need to configure your target provider first as bellow.')
            print(f'    chatchat config {provider}.api_key=YOUR_API_KEY')
            exit(-1)

    def build_client_messages(self, *, model, messages, generation_options, tools=None):
        jmsg = {
            'model': model if model else self.model,
            "messages": messages,
        }
        thinking = 'enabled' if generation_options.get('thinking') else 'disabled'
        jmsg['thinking'] = {'type': thinking}
        if generation_options.get('stream'):
            jmsg['stream'] = True
        if tools:
            jmsg['tools'] = tools.to_dict()
        return jmsg

    def has_tool_calls(self, message: dict):
        return bool(message.get(self._tool_calls_key))

    def handle_tool_calls(self, message, tools):
        tool_calls = message[self._tool_calls_key]
        tool_result_messages = []
        for tool_call in tool_calls:
            func = tool_call['function']
            name = func['name']
            args = json.loads(func['arguments'])
            id = tool_call[self._tool_call_id_key]
            tool = tools[name]
            tool_result = tool(**args)
            tool_content = tool_result
            if isinstance(tool_result, types.GeneratorType):
                tool_content = ''
                for chunk in tool_result:
                    tool_content += chunk
            tool_result_messages.append({'role': 'tool', 'content': tool_content, 'tool_call_id': id})
        return tool_result_messages

    def send_messages_impl(self, url, jmsg, tools=None):
        r = self.client.post(url, json=jmsg)
        r = r.json()
        r = r['choices'][0]['message']

        message = {}
        self._parse_role(r, message)
        text = self._parse_reasoning_content(r, message, streaming=False)
        text += self._parse_content(r, message, streaming=False)
        text += self._parse_tool_calls(r, message, streaming=False)

        if self.has_tool_calls(message):
            jmsg['messages'].append(message)
            tool_result_messages = self.handle_tool_calls(r, tools)
            jmsg['messages'] += tool_result_messages
            text += self.send_messages_impl(url, jmsg)
            return text

        jmsg['messages'].append(message)
        return text

    def _parse_role(self, r: dict, message: dict):
        role = message.get(self._role_key, None)
        if not role:
            message[self._role_key] = r[self._role_key]

    def _parse_reasoning_content(self, r: dict, message: dict, streaming=False):
        reasoning_content = r.get(self._reasoning_content_key)
        if not reasoning_content:
            return ''
        if streaming:
            if message.get(self._reasoning_content_key):
                message[self._reasoning_content_key] += reasoning_content
                return reasoning_content
            else:
                message[self._reasoning_content_key] = reasoning_content
                return f'\n<think>\n{reasoning_content}'
        else:
            message[self._reasoning_content_key] = reasoning_content
            return f'\n<think>\n{reasoning_content}\n</think>\n'

    def _parse_content(self, r: dict, message: dict, streaming=False):
        content = r.get(self._content_key)
        if not content:
            return ''
        if streaming:
            if message.get(self._content_key):
                message[self._content_key] += content
                return content
            else:
                message[self._content_key] = content
                return f'\n</think>\n{content}' if message.get(self._reasoning_content_key) else content
        else:
            message[self._content_key] = content
            return content

    def _parse_tool_calls(self, r: dict, message: dict, streaming=True):
        tool_calls: list[dict] = r.get(self._tool_calls_key)
        if not tool_calls:
            return ''
        if streaming:
            msg_tool_calls: list[dict] = message.get(self._tool_calls_key, [])
            for tool_call in tool_calls:
                target_tool_call = None
                for msg_tool_call in msg_tool_calls:
                    if msg_tool_call.get('id') == tool_call.get('id'):
                        target_tool_call = msg_tool_call
                        break

                if target_tool_call is None:
                    if self._tool_call_index_key in tool_call and tool_call[self._tool_call_index_key] < len(msg_tool_calls):
                        target_tool_call = msg_tool_calls[tool_call[self._tool_call_index_key]]
                    elif self._tool_call_id_key not in tool_call and msg_tool_calls:
                        target_tool_call = msg_tool_calls[-1]

                if target_tool_call:
                    tool_call_func = tool_call['function']
                    target_tool_call_func = target_tool_call['function']
                    for name, value in tool_call_func.items():
                        if name in target_tool_call_func:
                            target_tool_call_func[name] += value
                        else:
                            target_tool_call_func[name] = value
                else:
                    msg_tool_calls.append(tool_call)
                    message[self._tool_calls_key] = msg_tool_calls
        else:
            message[self._tool_calls_key] = tool_calls
        return ''

    def send_messages_stream_impl(self, url, jmsg, tools=None):
        message = {}
        with self.client.stream('POST', url, json=jmsg) as r:
            for chunk in r.iter_lines():
                if not chunk:
                    continue

                # remove chunk prefix: 'data: '
                chunk = chunk[6:]
                if chunk == '[DONE]':
                    break

                # openrouter
                if chunk == 'ROUTER PROCESSING':
                    continue

                try:
                    chunk = json.loads(chunk)
                except Exception as e:
                    print(f'{e}\njson.loads failed, chunk data:\n{chunk}')
                    exit(1)

                chunk_response = chunk['choices'][0]['delta']

                self._parse_role(chunk_response, message)
                text = self._parse_reasoning_content(chunk_response, message, streaming=True)
                text += self._parse_content(chunk_response, message, streaming=True)
                text += self._parse_tool_calls(chunk_response, message, streaming=True)

                yield text

        jmsg['messages'].append(message)
        if self.has_tool_calls(message):
            tool_result_messages = self.handle_tool_calls(message, tools)
            jmsg['messages'] += tool_result_messages
            yield from self.send_messages_stream_impl(url, jmsg, tools=tools)

    def send_messages(self, messages, *, generation_options={}, model=None, tools=None):
        jmsg = self.build_client_messages(
            model=model, messages=messages, generation_options=generation_options, tools=tools,
        )
        url = '/chat/completions'

        if not generation_options.get('stream', False):
            return self.send_messages_impl(url, jmsg, tools=tools)
        else:
            return self.send_messages_stream_impl(url, jmsg, tools=tools)

    def complete(self, prompt, *, model=None, generation_options={}):
        message = {'role': 'user', 'content': prompt}
        messages = [message] if self.instruction is None else [self.system_message(), message]
        return self.send_messages(messages, model=model, generation_options=generation_options)

    def clear(self):
        self.history = [self.system_message()] if self.instruction else []

    def chat(self, text, *, model=None, history=None, generation_options={}, tools=None):
        message = {'role': 'user', 'content': text}
        messages = history if history else self.history
        messages.append(message)
        return self.send_messages(messages, model=model, generation_options=generation_options, tools=tools)

def dynamic_import_client(provider):
    if provider not in __providers__:
            print(f'provider `{provider}` is currently not supported!')
            print(f'supported providers: {__providers__}')
            exit(-1)
    client_module = import_module(f'chatchat.providers.{provider}')
    client_class = getattr(client_module, f'{provider.capitalize()}Client')
    return client_class

class Client:
    def __init__(self, provider, model, instruction=None, http_options={}):
        client_class = dynamic_import_client(provider)
        self.client: BaseClient = client_class(model=model, instruction=instruction, http_options=http_options)

        self.chat = self.client.chat
        self.complete = self.client.complete
        self.clear = self.client.clear

    @property
    def history(self):
        return self.client.history

    @property
    def instruction(self):
         return self.client.instruction

    @instruction.setter
    def instruction(self, value):
         self.client.instruction = value
