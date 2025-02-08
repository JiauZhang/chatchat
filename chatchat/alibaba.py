from chatchat.base import Base
import httpx

__vendor__ = 'alibaba'
__vendor_keys__ = ('api_key',)

class Completion(Base):
    def __init__(self, model='qwen-turbo', proxy=None, timeout=None):
        super().__init__(__vendor__, __vendor_keys__)

        self.api_key = self.secret_data[__vendor_keys__[0]]
        self.model = model
        self.api = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }

    def send_message(self, messages: list):
        jmsg = {
            'model': self.model,
            "input": {
                "messages": messages,
            },
            "parameters": {
                "result_format": "message"
            }
        }
        r = self.client.post(self.api, headers=self.headers, json=jmsg)
        return r.json()

    def create(self, message):
        jmsg = [{
            "role": "user",
            "content": message,
        }]
        return self.send_message(jmsg)

class Chat(Completion):
    def __init__(self, model='qwen-turbo', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message):
        self.history.append({
            'role': 'user',
            'content': message,
        })

        r = self.send_message(self.history)
        assistant_output = r['output']['choices'][0]['message']
        self.history.append(assistant_output)

        return r
