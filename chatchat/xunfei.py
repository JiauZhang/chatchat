from chatchat.base import Base
from .vendor import __vendor_info__

__vendor__ = 'xunfei'
__vendor_keys__ = __vendor_info__[__vendor__]

class Completion(Base):
    def __init__(self, model='lite', client_kwargs={}):
        self.model_service = {
            'deepseek-r1': 'xdeepseekr1',
            'deepseek-v3': 'xdeepseekv3',
        }

        if model in self.model_service:
            super().__init__(__vendor__, __vendor_keys__[1:], client_kwargs=client_kwargs)
            # https://training.xfyun.cn/modelService
            self.model = self.model_service[model]
            self.api = 'http://maas-api.cn-huabei-1.xf-yun.com/v1/chat/completions'
            self.api_key = self.secret_data[__vendor_keys__[1]]
        else:
            super().__init__(__vendor__, __vendor_keys__[:1], client_kwargs=client_kwargs)
            self.model = model
            # https://console.xfyun.cn/services/cbm
            self.api_key = self.secret_data[__vendor_keys__[0]]
            self.api = 'https://spark-api-open.xf-yun.com/v1/chat/completions'

        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }

    def send_messages(self, messages: list):
        jmsg = {
            'model': self.model,
            "messages": messages,
        }
        url = self.api
        r = self.client.post(url, headers=self.headers, json=jmsg)
        r = r.json()
        r = self.response(r, ('choices', 0, 'message', 'content'))
        return r

    def create(self, message, stream=False):
        messages = [{
            "role": "user",
            "content": message,
        }]
        return self.send_messages(messages)

class Chat(Completion):
    def __init__(self, model='lite', history=[], client_kwargs={}):
        super().__init__(model=model, client_kwargs=client_kwargs)
        self.history = history

    def chat(self, message, stream=False):
        self.history.append({
            "role": "user", "content": message
        })
        r = self.send_messages(self.history)
        if r.text:
            self.history.append(r['choices'][0]['message'])

        return r
