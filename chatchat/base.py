import pathlib, os, httpx
from conippets import json

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

class Base():
    def __init__(self, vendor, base_url, model=None, client_kwargs={}):
        self.vendor = vendor
        if not os.path.exists(__secret_file__):
            json.write(__secret_file__, {})

        secret_data = json.read(__secret_file__)
        self.verify_secret_data(secret_data, self.vendor)
        self.secret_file = __secret_file__
        self.secret_data = secret_data[self.vendor]
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

    def verify_secret_data(self, secret_data, vendor):
        has_vendor = vendor in secret_data
        has_key = False
        if has_vendor:
            vendor_data = secret_data[vendor]
            has_key = 'api_key' in vendor_data
        if not (has_vendor and has_key):
            print('You need to configure your target vendor first as bellow.')
            print(f'    chatchat config {vendor}.api_key=YOUR_API_KEY')
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
                    chunk = json.loads(chunk)
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
        return self.send_messages([message], model=model, stream=stream, record=False)

    def clear(self):
        self.history = []

    def chat(self, text, model=None, history=None, stream=False, generation_kwargs={}):
        message = self.make_message('user', text)
        messages = history if history else self.history
        messages.append(message)
        return self.send_messages(messages, model=model, stream=stream, record=True)