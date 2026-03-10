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
    def __init__(self, provider, base_url, model=None, instruction=None, client_kwargs={}):
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
            base_url=base_url, **client_kwargs, headers={
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

    def make_message(self, role, text):
        message = {'role': role, 'content': text}
        return message

    def send_messages_impl(self, url, jmsg, record=False):
        r = self.client.post(url, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        if record and (text := r.text):
            jmsg['messages'].append(self.make_message('assistant', text))
        return r

    def send_messages_stream_impl(self, url, jmsg, record=False):
        with self.client.stream('POST', url, json=jmsg) as r:
            completion = ''
            for chunk in r.iter_lines():
                if chunk:
                    # remove chunk prefix: 'data: '
                    chunk = chunk[6:]
                    try:
                        chunk = json.loads(chunk)
                    except Exception as e:
                        print(f'{e}\njson.loads failed, chunk data:\n{chunk}')
                        exit(1)

                    chunk_response = Response(chunk, ('choices', 0, 'finish_reason'))
                    if chunk_response.text == 'stop':
                        if record and completion:
                            jmsg['messages'].append(self.make_message('assistant', completion))
                        break
                    chunk_response.text_keys = ('choices', 0, 'delta', 'content')
                    if text := chunk_response.text:
                        completion += text
                    yield chunk_response

    def send_messages(self, messages: list, model=None, record=False, stream=False):
        jmsg = {
            'model': model if model else self.model,
            "messages": messages,
        }
        url = '/chat/completions'

        if not stream:
            return self.send_messages_impl(url, jmsg, record=record)
        else:
            jmsg['stream'] = True
            return self.send_messages_stream_impl(url, jmsg, record=record)

    def response(self, raw_response, text_keys):
        if not isinstance(raw_response, dict):
            raw_response = {'raw_response': raw_response}
        return Response(raw_response, text_keys)

    def complete(self, prompt, model=None, stream=False, generation_kwargs={}):
        message = self.make_message('user', prompt)
        messages = [message] if self._instruction is None else [self.history[0], message]
        return self.send_messages(messages, model=model, stream=stream, record=False)

    @property
    def instruction(self):
        return self._instruction

    @instruction.setter
    def instruction(self, value):
        self._instruction = value
        self.clear()

    def clear(self):
        self.history = [self.make_message('system', self._instruction)] if self._instruction else []

    def chat(self, text, model=None, history=None, stream=False, generation_kwargs={}):
        message = self.make_message('user', text)
        messages = history if history else self.history
        messages.append(message)
        return self.send_messages(messages, model=model, stream=stream, record=True)


def dynamic_import_client(provider):
    if provider not in __providers__:
            print(f'provider `{provider}` is currently not supported!')
            print(f'supported providers: {__providers__}')
            exit(-1)
    client_module = import_module(f'chatchat.providers.{provider}')
    client_class = getattr(client_module, f'{provider.capitalize()}Client')
    return client_class

class Client:
    def __init__(self, provider, model=None, instruction=None, client_kwargs={}):
        client_class = dynamic_import_client(provider)
        self.client = client_class(model=model, instruction=instruction, client_kwargs=client_kwargs)

    def complete(self, prompt, model=None, stream=False, generation_kwargs={}):
        return self.client.complete(
            prompt, model=model, stream=stream, generation_kwargs=generation_kwargs,
        )

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

    def chat(self, text, model=None, history=None, stream=False, generation_kwargs={}):
        return self.client.chat(
            text, model=model, history=history, stream=stream,
            generation_kwargs=generation_kwargs,
        )
