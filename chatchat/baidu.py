from chatchat.base import Base
import httpx

__vendor__ = 'baidu'
__vendor_keys__ = ('app_id',)

class Completion(Base):
    def __init__(self, model='ernie-speed-8k', proxy=None, timeout=None):
        super().__init__(__vendor__, __vendor_keys__)

        self.app_id = self.secret_data[__vendor_keys__[0]]
        # https://console.bce.baidu.com/qianfan/ais/console/onlineService
        self.model_set = set([
            'ernie-4.0-8k-latest', 'ernie-4.0-8k', 'ernie-speed-8k',
            'deepseek-v3', 'deepseek-r1',
        ])

        if model not in self.model_set:
            raise RuntimeError(f'supported chat type: {self.model_set}')
        self.model = model
        self.api = 'https://qianfan.baidubce.com/v2/chat/completions'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
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

    def create(self, message):
        messages = [
            {
                "role": "user",
                "content": message,
            }
        ]
        return self.send_messages(messages)

class Chat(Completion):
    def __init__(self, model='ernie-speed-8k', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message):
        self.history.append({
            "role": "user",
            "content": message,
        })
        r = self.send_messages(self.history)
        if 'result' in r:
            self.history.append({
                "role": "assistant",
                "content": r['result']
            })

        return r
