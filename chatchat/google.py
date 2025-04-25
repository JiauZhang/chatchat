from chatchat.base import Base
import httpx

__vendor__ = 'google'
__vendor_keys__ = ('api_key',)

class Completion(Base):
    def __init__(self, model='gemini-2.0-flash', proxy=None, timeout=None):
        super().__init__(__vendor__, __vendor_keys__)

        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.host = 'https://generativelanguage.googleapis.com/v1beta/models'
        self.chat_url = f'{self.host}/{model}:generateContent'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
        self.headers = {'Content-Type': 'application/json'}
        self.params = {'key': self.api_key}
        self.history = []

    def message_template(self, role, text):
        message = {
            "role": role,
            "parts": [{"text": text}],
        }
        return message

    def create(self, message):
        self.history = [self.message_template('user', message)]
        jmsg = {'contents': self.history}
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg, params=self.params)
        return r.json()

class Chat(Completion):
    def __init__(self, model='gemini-2.0-flash', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message):
        self.history.append(self.message_template('user', message))
        jmsg = {'contents': self.history}
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg, params=self.params)
        r = r.json()

        if 'candidates' in r:
            assistant_output = r['candidates'][0]['content']
            self.history.append(assistant_output)

        return r
