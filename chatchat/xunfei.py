from chatchat.base import Base
import httpx

__vendor__ = 'xunfei'
__vendor_keys__ = ('api_key',) # https://console.xfyun.cn/services/cbm

class Completion(Base):
    def __init__(self, model='lite', proxy=None, timeout=None):
        super().__init__(__vendor__, __vendor_keys__)

        self.model = model
        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.api = 'https://spark-api-open.xf-yun.com/v1/chat/completions'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
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
        return r.json()

    def create(self, message, stream=False):
        messages = [{
            "role": "user",
            "content": message,
        }]
        return self.send_messages(messages)

class Chat(Completion):
    def __init__(self, model='lite', history=[], proxy=None, timeout=None):
        super().__init__(model=model)
        self.history = history

    def chat(self, message, stream=False):
        self.history.append({
            "role": "user", "content": message
        })
        r = self.send_messages(self.history)
        if 'choices' in r:
            self.history.append(r['choices'][0]['message'])

        return r
