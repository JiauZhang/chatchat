import pathlib, os, httpx
from conippets import json
from importlib import import_module
from chatchat.providers import __providers__

__secret_file__ = os.path.join(str(pathlib.Path.home()), '.chatchat.json')

class Response(dict):
    def __init__(self, raw_response, text_keys):
        super().__init__(**raw_response)
        self.text_keys = text_keys

    @property
    def text(self):
        text = self
        for key in self.text_keys:
            try:
                text = text[key]
            except:
                text = None
                break
        return text

class BaseClient():
    def __init__(self, provider, base_url, model=None, instruction=None, http_options={}):
        self.provider = provider
        self._instruction = instruction
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
        self.history = []
        self.clear()

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

    def make_message(self, role, text, thinking=False):
        content_type = 'content' if not thinking else 'reasoning_content'
        message = {'role': role, content_type: text}
        return message

    def build_client_messages(self, model, messages, generation_options):
        jmsg = {
            'model': model if model else self.model,
            "messages": messages,
        }
        if generation_options.get('stream'):
            jmsg['stream'] = True
        return jmsg

    def send_messages_impl(self, url, jmsg, record=False, thinking=False):
        r = self.client.post(url, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        if record and (text := r.text):
            jmsg['messages'].append(self.make_message('assistant', text))
        return r

    def send_messages_stream_impl(self, url, jmsg, record=False, thinking=False):
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
                        if record and completion:
                            jmsg['messages'].append({'role': 'assistant', content_type: completion})
                        break
                    try:
                        chunk = json.loads(chunk)
                    except Exception as e:
                        print(f'{e}\njson.loads failed, chunk data:\n{chunk}')
                        exit(1)

                    chunk_response = chunk['choices'][0]['delta']
                    if thinking and 'content' in chunk_response:
                        yield '\n</think>\n'
                        if record and completion:
                            jmsg['messages'].append({'role': 'assistant', content_type: completion})
                        content_type = 'content'
                        completion = ''
                        thinking = False

                    text = chunk_response[content_type]
                    if text:
                        completion += text
                    yield text

    def send_messages(self, messages, generation_options={}, model=None, record=False):
        jmsg = self.build_client_messages(model, messages, generation_options)
        url = '/chat/completions'
        thinking = generation_options.get('thinking')

        if not generation_options.get('stream', False):
            return self.send_messages_impl(url, jmsg, record=record, thinking=thinking)
        else:
            return self.send_messages_stream_impl(url, jmsg, record=record, thinking=thinking)

    def response(self, raw_response, text_keys):
        if not isinstance(raw_response, dict):
            raw_response = {'raw_response': raw_response}
        return Response(raw_response, text_keys)

    def complete(self, prompt, model=None, generation_options={}):
        message = self.make_message('user', prompt)
        messages = [message] if self._instruction is None else [self.history[0], message]
        return self.send_messages(messages, model=model, record=False, generation_options=generation_options)

    @property
    def instruction(self):
        return self._instruction

    @instruction.setter
    def instruction(self, value):
        self._instruction = value
        self.clear()

    def clear(self):
        self.history = [self.make_message('system', self._instruction)] if self._instruction else []

    def chat(self, text, model=None, history=None, generation_options={}):
        message = self.make_message('user', text)
        messages = history if history else self.history
        messages.append(message)
        return self.send_messages(messages, model=model, generation_options=generation_options, record=True)

def dynamic_import_client(provider):
    if provider not in __providers__:
            print(f'provider `{provider}` is currently not supported!')
            print(f'supported providers: {__providers__}')
            exit(-1)
    client_module = import_module(f'chatchat.providers.{provider}')
    client_class = getattr(client_module, f'{provider.capitalize()}Client')
    return client_class

class Client:
    def __init__(self, provider, model=None, instruction=None, http_options={}):
        client_class = dynamic_import_client(provider)
        self.client: BaseClient = client_class(model=model, instruction=instruction, http_options=http_options)

    def complete(self, prompt, model=None, generation_options={}):
        return self.client.complete(prompt, model=model, generation_options=generation_options)

    @property
    def history(self):
        return self.client.history

    @property
    def instruction(self):
         return self.client.instruction

    @instruction.setter
    def instruction(self, value):
         self.client.instruction = value

    def clear(self):
        self.client.clear()

    def chat(self, text, model=None, history=None, generation_options={}):
        return self.client.chat(text, model=model, history=history, generation_options=generation_options)
