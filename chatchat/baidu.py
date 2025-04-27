from chatchat.base import Base
from .vendor import __vendor_info__

__vendor__ = 'baidu'
__vendor_keys__ = __vendor_info__[__vendor__]

class Completion(Base):
    def __init__(self, model='ernie-speed-8k', client_kwargs={}):
        super().__init__(__vendor__, __vendor_keys__, client_kwargs=client_kwargs)

        self.app_id = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.api = 'https://qianfan.baidubce.com/v2/chat/completions'
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.app_id}',
        }

    def send_messages(self, messages):
        jmsg = {
            'model': self.model,
            "messages": messages,
        }
        url = self.api
        r = self.client.post(url, headers=self.headers, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        return r

    def create(self, message):
        messages = [{
            "role": "user",
            "content": message,
        }]
        r = self.send_messages(messages)
        return r

class Chat(Completion):
    def __init__(self, model='ernie-speed-8k', history=[], client_kwargs={}):
        super().__init__(model=model, client_kwargs=client_kwargs)
        self.history = history

    def chat(self, message):
        self.history.append({
            "role": "user",
            "content": message,
        })
        r = self.send_messages(self.history)
        if r.text: self.history.append({"role": "assistant", "content": r.text})
        return r