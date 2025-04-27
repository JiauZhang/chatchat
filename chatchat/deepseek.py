from chatchat.base import Base
from .vendor import __vendor_info__

__vendor__ = 'deepseek'
__vendor_keys__ = __vendor_info__[__vendor__]

class Completion(Base):
    def __init__(self, model='deepseek-chat', client_kwargs={}):
        super().__init__(__vendor__, __vendor_keys__, client_kwargs=client_kwargs)

        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.host = 'https://api.deepseek.com'
        self.model_url = f'{self.host}/models'
        self.chat_url = f'{self.host}/chat/completions'
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }

    def model_list(self):
        r = self.client.get(self.model_url, headers=self.headers)
        return r.json()

    def send_message(self, message, max_tokens=1024, temperature=1.0, top_p=1.0):
        jmsg = {
            'model': self.model,
            'messages': message,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
        }
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        return r

    def create(self, message, max_tokens=1024, temperature=1.0, top_p=1.0):
        jmsg = [{
            "role": "user",
            "content": message,
        }]
        return self.send_message(jmsg, max_tokens, temperature, top_p)

class Chat(Completion):
    def __init__(self, model='deepseek-chat', history=[], client_kwargs={}):
        super().__init__(model=model, client_kwargs=client_kwargs)
        self.history = history

    def chat(self, message, max_tokens=1024, temperature=1.0, top_p=1.0):
        self.history.append({
            'role': 'user',
            'content': message,
        })
        r = self.send_message(self.history, max_tokens, temperature, top_p)

        if r.text:
            assistant_output = r['choices'][0]['message']
            self.history.append(assistant_output)

        return r
