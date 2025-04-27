from chatchat.base import Base
from .vendor import __vendor_info__

__vendor__ = 'zhipu'
__vendor_keys__ = __vendor_info__[__vendor__]

class Completion(Base):
    def __init__(self, model='glm-4-flash', client_kwargs={}):
        super().__init__(__vendor__, __vendor_keys__, client_kwargs=client_kwargs)

        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }

    def send_message(self, message, max_tokens=1024, temperature=0.95, top_p=0.7, stream=False):
        jmsg = {
            'model': self.model,
            'messages': message,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
            'stream': stream,
        }
        r = self.client.post(self.url, headers=self.headers, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        return r

    def create(self, message, max_tokens=1024, temperature=0.95, top_p=0.7, stream=False):
        jmsg = [{
            "role": "user",
            "content": message,
        }]
        return self.send_message(jmsg, max_tokens, temperature, top_p, stream)

class Chat(Completion):
    def __init__(self, model='glm-4-flash', history=[], client_kwargs={}):
        super().__init__(model=model, client_kwargs=client_kwargs)
        self.history = history

    def chat(self, message, max_tokens=1024, temperature=0.95, top_p=0.7, stream=False):
        self.history.append({
            'role': 'user',
            'content': message,
        })
        r = self.send_message(self.history, max_tokens, temperature, top_p, stream)
        if r.text:
            assistant_output = r['choices'][0]['message']
            self.history.append(assistant_output)

        return r
