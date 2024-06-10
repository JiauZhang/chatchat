from chatchat.base import Base
import hashlib, hmac, json, time
from datetime import datetime
import httpx

class Completion(Base):
    def __init__(self, model='hunyuan-lite', proxy=None, timeout=None):
        super().__init__()

        plat = 'tencent'
        self.verify_secret_data(plat, ('secret_id', 'secret_key'))
        self.jdata = self.secret_data[plat]
        self.secret_id = self.jdata['secret_id']
        self.secret_key = self.jdata['secret_key']

        self.model_type = set([
            'hunyuan-lite',
            'hunyuan-standard',
            'hunyuan-standard-256K',
            'hunyuan-pro',
        ])
        if model not in self.model_type:
            raise RuntimeError(f'supported chat type: {list(self.model_type)}')
        self.model = model

        self.host = 'hunyuan.tencentcloudapi.com'
        self.endpoint = f'https://{self.host}'
        self.client = httpx.Client(proxy=proxy, timeout=timeout)

    def encode_message(self, jmsg):
        # step 1
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        action = 'ChatCompletions'
        host = 'hunyuan.tencentcloudapi.com'
        payload = json.dumps(jmsg)
        canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (http_request_method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)

        # step 2
        service = "hunyuan"
        algorithm = "TC3-HMAC-SHA256"
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        credential_scope = date + "/" + service + "/" + "tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = (algorithm + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)

        # step 3
        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        # step 4
        authorization = (algorithm + " " +
                        "Credential=" + self.secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)

        headers = {
            'Authorization': authorization,
            'Content-Type': 'application/json; charset=utf-8',
            'Host': self.host,
            'X-TC-Action': 'ChatCompletions',
            'X-TC-Timestamp': str(timestamp),
            'X-TC-Version': '2023-09-01',
            'X-TC-Region': 'ap-beijing',
        }

        return headers, payload

    def send_message(self, history: list):
        jmsg = {
            "TopP": 1,
            "Temperature": 1,
            "Model": self.model,
            "Messages": history,
            "Stream": False,
        }
        headers, payload = self.encode_message(jmsg)
        r = self.client.post(self.endpoint, headers=headers, data=payload)
        return r.json()

    def create(self, message, stream=False):
        jmsg = [{
            "Role": "user",
            "Content": message,
        }]
        return self.send_message(jmsg)

class Chat(Completion):
    def __init__(self, model='hunyuan-lite', history=[], proxy=None, timeout=None):
        super().__init__(model=model, proxy=proxy, timeout=timeout)
        self.history = history

    def chat(self, message):
        self.history.append({
            'Role': 'user',
            'Content': message,
        })

        r = self.send_message(self.history)
        if 'Choices' in r['Response']:
            assistant_output = r['Response']['Choices'][0]['Message']
            self.history.append(assistant_output)

        return r
