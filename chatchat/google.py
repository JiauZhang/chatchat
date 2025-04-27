from chatchat.base import Base
from .vendor import __vendor_info__

__vendor__ = 'google'
__vendor_keys__ = __vendor_info__[__vendor__]

class Completion(Base):
    def __init__(self, model='gemini-2.0-flash', client_kwargs={}):
        super().__init__(__vendor__, __vendor_keys__, client_kwargs=client_kwargs)

        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.host = 'https://generativelanguage.googleapis.com/v1beta/models'
        self.chat_url = f'{self.host}/{model}:generateContent'
        self.headers = {'Content-Type': 'application/json'}
        self.params = {'key': self.api_key}

    def message_template(self, role, text):
        message = {
            "role": role,
            "parts": [{"text": text}],
        }
        return message

    def send_message(self, message):
        jmsg = {'contents': message}
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg, params=self.params)
        r = r.json()
        r = self.response(r, ('candidates', 0, 'content', 'parts', 0, 'text'))
        return r

    def create(self, message):
        msg = [self.message_template('user', message)]
        return self.send_message(msg)

class Chat(Completion):
    def __init__(self, model='gemini-2.0-flash', history=[], client_kwargs={}):
        super().__init__(model=model, client_kwargs=client_kwargs)
        self.history = history

    def chat(self, message):
        self.history.append(self.message_template('user', message))
        r = self.send_message(self.history)

        if r.text:
            assistant_output = r['candidates'][0]['content']
            self.history.append(assistant_output)

        return r
