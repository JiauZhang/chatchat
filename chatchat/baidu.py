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

    def send_messages(self, messages: list):
        jmsg = {
            'model': self.model,
            "messages": messages,
        }
        url = self.api
        r = self.client.post(url, headers=self.headers, json=jmsg)
        return r.json()

    def text(self, response, history=False):
        if 'choices' in response:
            content = response['choices'][0]['message']['content']
            if history: self.history.append({
                "role": "assistant",
                "content": content,
            })
            return content
        print(response)
        return None

    def create(self, message):
        messages = [
            {
                "role": "user",
                "content": message,
            }
        ]
        r = self.send_messages(messages)
        return self.text(r, history=False)

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
        return self.text(r, history=True)
