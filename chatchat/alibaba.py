from chatchat.base import Base
import httpx, time

class Completion(Base):
    def __init__(self, jfile, model='qwen-turbo'):
        # https://dashscope.console.aliyun.com/dashboard?apiKey=all&model=qwen-turbo
        self.model_type = set([
            'qwen-turbo',
            'qwen-plus',
            'qwen-max',
        ])

        if model not in self.model_type:
            raise RuntimeError(f'supported chat type: {list(self.model_type)}')
        self.model = model

        self.jfile = jfile
        self.jdata = self.load_json(jfile)['alibaba']
        self.api = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
        self.client = httpx.Client()
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.jdata["api_key"]}',
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
    def __init__(self, jfile, model='qwen-turbo', history=[]):
        super().__init__(jfile, model=model)
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
