from wsgiref.handlers import format_date_time
from urllib.parse import urlencode
from chatchat.base import Base
import base64, hashlib, hmac
from datetime import datetime
from time import mktime
import websocket, json, ssl

class Completion(Base):
    def __init__(self, model='Spark Lite'):
        super().__init__()

        # https://console.xfyun.cn/services/bm2
        # "xunfei": {
        #     "app_id": "x",
        #     "api_secret": "y",
        #     "api_key": "z"
        # }
        plat = 'xunfei'
        self.verify_secret_data(plat, ('api_key', 'api_secret', 'app_id'))
        self.jdata = self.secret_data[plat]

        # https://www.xfyun.cn/doc/spark/Web.html#_1-接口说明
        self.api_list = {
            'Spark3.5 Max': {
                'path': '/v3.5/chat',
                'domain': 'generalv3.5',
            },
            'Spark Pro': {
                'path': '/v3.1/chat',
                'domain': 'generalv3',
            },
            'Spark V2.0': {
                'path': '/v2.1/chat',
                'domain': 'generalv2',
            },
            'Spark Lite': {
                'path': '/v1.1/chat',
                'domain': 'general',
            },
        }

        if model not in self.api_list:
            raise RuntimeError(f'supported chat type: {self.api_list.keys()}')
        self.host = 'spark-api.xf-yun.com'
        self.api = self.api_list[model]
        self.path = self.api['path']
        self.domain = self.api['domain']

        self.update_interval = 150
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        websocket.enableTrace(False)
        self.answer = ''

    def create_url(self):
        # https://www.xfyun.cn/doc/spark/general_url_authentication.html
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_raw = f'host: {self.host}\ndate: {date}\nGET {self.path} HTTP/1.1'
        signature_sha = hmac.new(
            self.jdata['api_secret'].encode('utf-8'),
            signature_raw.encode('utf-8'),
            digestmod=hashlib.sha256,
        ).digest()
        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')
        authorization_raw = ', '.join([
            f'api_key="{self.jdata["api_key"]}"',
            'algorithm="hmac-sha256"',
            'headers="host date request-line"',
            f'signature="{signature_sha_base64}"',
        ])
        authorization = base64.b64encode(authorization_raw.encode('utf-8')).decode(encoding='utf-8')
        query = {
            "authorization": authorization,
            "date": date,
            "host": self.host
        }
        url = f'wss://{self.host}{self.path}?{urlencode(query)}'

        return url

    def on_error(self, wsapp, error):
        print(f'Error: {error}')

    def on_close(self, wsapp, close_status_code, close_msg):
        ...

    def on_open(self, wsapp):
        data = json.dumps(wsapp.json)
        wsapp.send(data)

    def on_message(self, wsapp, message):
        data = json.loads(message)
        code = data['header']['code']
        if code != 0:
            print(f'Request Error: {code}, {data}')
            wsapp.close()
        else:
            choices = data["payload"]["choices"]
            status = choices["status"]
            content = choices["text"][0]["content"]
            self.answer += content
            if wsapp.stream: print(content, end='')
            if status == 2:
                wsapp.close()

    def make_message(self, history: list):
        jmsg = {
            "header": {
                "app_id": self.jdata['app_id'],
            },
            "parameter": {
                "chat": {
                    "domain": self.domain,
                }
            },
            "payload": {
                "message": {
                    "text": history
                }
            }
        }
        return jmsg

    def create(self, message, stream=False):
        jmsg = self.make_message([{
            "role": "user", "content": message
        }])

        self.answer = ''
        url = self.create_url()
        ws = websocket.WebSocketApp(
            url, on_message=self.on_message, on_error=self.on_error,
            on_close=self.on_close, on_open=self.on_open,
        )
        ws.json = jmsg
        ws.stream = stream
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        return self.answer

class Chat(Completion):
    def __init__(self, model='Spark Lite', history=[]):
        super().__init__(model=model)
        self.history = history

    def chat(self, message, stream=False):
        self.history.append({
            "role": "user", "content": message
        })
        jmsg = self.make_message(self.history)

        self.answer = ''
        url = self.create_url()
        ws = websocket.WebSocketApp(
            url, on_message=self.on_message, on_error=self.on_error,
            on_close=self.on_close, on_open=self.on_open,
        )
        ws.json = jmsg
        ws.stream = stream
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

        self.history.append({
            "role": "assistant", "content": self.answer,
        })

        return self.answer
