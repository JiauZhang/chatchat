from chatchat.base import Base
import httpx, time

class Completion(Base):
    def __init__(self, model='ERNIE-Speed-8K', proxy=None, timeout=None):
        super().__init__()

        # https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application
        #     {
        #         "baidu": {
        #             "api_key": "x",
        #             "secret_key": "y",
        #             "expires_in": "z",
        #             "access_token": "k"
        #         }
        #     }
        plat = 'baidu'
        self.verify_secret_data(plat, ('api_key', 'secret_key'))
        self.jdata = self.secret_data[plat]
        self.update_interval = 3600

        # https://console.bce.baidu.com/qianfan/ais/console/onlineService
        self.api_list = {
            'ERNIE-Speed-8K': 'ernie_speed',
            'ERNIE-Speed-128K': 'ernie-speed-128k',
            'ERNIE-Speed-AppBuilder': 'ai_apaas',
            'ERNIE-Lite-8K': 'ernie-lite-8k',
            'ERNIE-Lite-8K-0922': 'eb-instant',
            'ERNIE-Bot-turbo-0922': 'eb-instant',
            'ERNIE-Tiny-8K': 'ernie-tiny-8k',
            'Yi-34B-Chat': 'yi_34b_chat',
        }

        if model not in self.api_list:
            raise RuntimeError(f'supported chat type: {self.api_list.keys()}')
        self.api = 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/' + self.api_list[model]
        self.client = httpx.Client(proxy=proxy, timeout=timeout)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        self.update_access_token()

    def update_access_token(self):
        if 'expires_in' not in self.jdata or not self.jdata['expires_in'] \
            or self.jdata['expires_in'] < time.time() + self.update_interval:
            # https://cloud.baidu.com/doc/WENXINWORKSHOP/s/Ilkkrb0i5
            url = "https://aip.baidubce.com/oauth/2.0/token"
            params = {
                "grant_type": "client_credentials",
                "client_id": self.jdata['api_key'],
                "client_secret": self.jdata['secret_key'],
            }
            # {
            #     "refresh_token":"a",
            #     "expires_in": b,
            #     "session_key": "c",
            #     "access_token": "d",
            #     "scope": "e",
            #     "session_secret": "f"
            # }
            cur_time = time.time()
            r = self.client.post(url, headers=self.headers, params=params).json()
            self.jdata['access_token'] = r['access_token']
            self.jdata['expires_in'] = cur_time + float(r['expires_in'])
            jdata = self.load_json(self.jfile)
            jdata.update({'baidu': self.jdata})
            self.write_json(self.jfile, jdata)

    def get_access_token(self):
        self.update_access_token()
        return self.jdata['access_token']

    def send_messages(self, messages: list):
        jmsg = {"messages": messages}
        url = f'{self.api}?access_token={self.get_access_token()}'
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
    def __init__(self, model='ERNIE-Speed-8K', history=[], proxy=None, timeout=None):
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
