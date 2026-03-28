import pathlib, os, httpx, types
from conippets import json
from importlib import import_module
from chatchat.providers import __providers__

__secret_file__ = os.path.join(str(pathlib.Path.home()), '.chatchat.json')

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

    def is_tool_calls(self, message):
        return 'tool_calls' in message

    def handle_tool_calls(self, message, tools):
        tool_calls = message['tool_calls']
        tool_result_messages = []
        for tool_call in tool_calls:
            func = tool_call['function']
            name = func['name']
            args = json.loads(func['arguments'])
            id = tool_call['id']
            tool = tools[name]
            tool_result = tool(**args)
            tool_content = tool_result
            if isinstance(tool_result, types.GeneratorType):
                tool_content = ''
                for chunk in tool_result:
                    tool_content += chunk
            tool_result_messages.append({'role': 'tool', 'content': tool_content, 'tool_call_id': id})
        return tool_result_messages

    def send_messages_impl(self, url, jmsg, thinking=False, tools=None):
        r = self.client.post(url, json=jmsg)
        r = r.json()
        r = r['choices'][0]['message']

        if self.is_tool_calls(r):
            jmsg['messages'].append(r)
            text = ''
            if thinking:
                text = f'\n<think>\n{r['reasoning_content']}\n</think>\n'
            # text += r['content'] # tool call content
            tool_result_messages = self.handle_tool_calls(r, tools)
            jmsg['messages'] += tool_result_messages
            text += self.send_messages_impl(url, jmsg, thinking=thinking)
            return text

        jmsg['messages'].append(r)
        text = ''
        if thinking:
            text = f'\n<think>\n{r['reasoning_content']}\n</think>\n'
        text += r['content']
        return text

    def send_messages_stream_impl(self, url, jmsg, thinking=False, tools=None):
        need_tool_calls = False
        message = {'role': 'assistant'}
        thinking_done = not thinking
        with self.client.stream('POST', url, json=jmsg) as r:
            completion = ''
            content_type = 'content' if not thinking else 'reasoning_content'

            if thinking:
                yield '\n<think>\n'

            for chunk in r.iter_lines():
                if chunk:
                    # remove chunk prefix: 'data: '
                    chunk = chunk[6:]

                    if chunk == '[DONE]':
                        if completion:
                            message[content_type] = completion
                        break
                    try:
                        chunk = json.loads(chunk)
                    except Exception as e:
                        print(f'{e}\njson.loads failed, chunk data:\n{chunk}')
                        exit(1)

                    chunk_response = chunk['choices'][0]['delta']
                    if  not thinking_done and thinking and 'content' in chunk_response:
                        yield '\n</think>\n'
                        if completion:
                            message[content_type] = completion
                        content_type = 'content'
                        completion = ''
                        thinking_done = True

                    if self.is_tool_calls(chunk_response):
                        message.update(chunk_response)
                        need_tool_calls = True
                        continue

                    text = chunk_response[content_type]
                    if text:
                        completion += text
                    yield text

        jmsg['messages'].append(message)
        if need_tool_calls:
            tool_result_messages = self.handle_tool_calls(message, tools)
            jmsg['messages'] += tool_result_messages
            yield from self.send_messages_stream_impl(url, jmsg, thinking=thinking, tools=tools)

    def send_messages(self, messages, *, generation_options={}, model=None, tools=None):
        jmsg = self.build_client_messages(
            model=model, messages=messages, generation_options=generation_options, tools=tools,
        )
        url = '/chat/completions'
        thinking = generation_options.get('thinking')

        if not generation_options.get('stream', False):
            return self.send_messages_impl(url, jmsg, thinking=thinking, tools=tools)
        else:
            return self.send_messages_stream_impl(url, jmsg, thinking=thinking, tools=tools)

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
