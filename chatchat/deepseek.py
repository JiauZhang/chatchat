from chatchat.base import Base
import httpx

class Completion(Base):
    def __init__(self, model='deepseek-chat', proxy=None, timeout=None):
        super().__init__()

        plat = 'deepseek'
        self.verify_secret_data(plat, ('api_key',))
        self.jdata = self.secret_data[plat]

        self.model_type = set([
            'deepseek-chat',
            'deepseek-coder',
        ])

        if model not in self.model_type:
            raise RuntimeError(f'supported chat type: {list(self.model_type)}')
        self.model = model

        self.host = 'https://api.deepseek.com'
        self.model_url = f'{self.host}/models'
        self.chat_url = f'{self.host}/chat/completions'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.jdata["api_key"]}',
        }

    def model_list(self):
        r = self.client.get(self.model_url, headers=self.headers)
        return r.json()

    def create(self, message, max_tokens=1024, temperature=1.0, top_p=1.0):
        jmsg = {
            'model': self.model,
            'messages': [{
                "role": "user",
                "content": message,
            }],
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
        }
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg)
        return r.json()

class Chat(Completion):
    def __init__(self, model='deepseek-chat', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message, max_tokens=1024, temperature=1.0, top_p=1.0):
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
        }
        r = self.client.post(self.chat_url, headers=self.headers, json=jmsg)
        r = r.json()

        if 'choices' in r:
            assistant_output = r['choices'][0]['message']
            self.history.append(assistant_output)

        return r
