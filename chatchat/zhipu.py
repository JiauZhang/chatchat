from chatchat.base import Base
import httpx

class Completion(Base):
    def __init__(self, model='glm-4-flash', proxy=None, timeout=None):
        super().__init__()

        plat = 'zhipu'
        self.verify_secret_data(plat, ('api_key',))
        self.jdata = self.secret_data[plat]

        self.model_type = set([
            'glm-4-0520',
            'glm-4',
            'glm-4-air',
            'glm-4-airx',
            'glm-4-flash',
            'glm-4v',
            'glm-3-turbo',
        ])

        if model not in self.model_type:
            raise RuntimeError(f'supported chat type: {list(self.model_type)}')
        self.model = model

        self.url = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.jdata["api_key"]}',
        }

    def create(self, message, max_tokens=1024, temperature=0.95, top_p=0.7, stream=False):
        jmsg = {
            'model': self.model,
            'messages': [{
                "role": "user",
                "content": message,
            }],
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
            'stream': stream,
        }
        r = self.client.post(self.url, headers=self.headers, json=jmsg)
        return r.json()

class Chat(Completion):
    def __init__(self, model='glm-4-flash', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message, max_tokens=1024, temperature=0.95, top_p=0.7, stream=False):
        self.history.append({
            'role': 'user',
            'content': message,
        })

        jmsg = {
            'model': self.model,
            'messages': self.history,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
            'stream': stream,
        }
        r = self.client.post(self.url, headers=self.headers, json=jmsg)
        r = r.json()

        if 'choices' in r:
            assistant_output = r['choices'][0]['message']
            self.history.append(assistant_output)

        return r
