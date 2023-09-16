import chatchat.utils as utils
import httpx, json, time

class Completion():
    def __init__(self, jfile):
        # jfile: https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application
        #     {
        #         "baidu": {
        #             "api_key": "x",
        #             "secret_key": "y",
        #             "expires_in": "z",
        #             "access_token": "k"
        #         }
        #     }
        self.jfile = jfile
        self.jdata = utils.load_json(jfile)['baidu']
        self.update_interval = 3600
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        if "api_key" not in self.jdata or "secret_key" not in self.jdata:
            raise RuntimeError(f'please check <baidu> api_key and secret_key in {jfile}')
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
            r = httpx.post(url, headers=self.headers, params=params).json()
            self.jdata['access_token'] = r['access_token']
            self.jdata['expires_in'] = cur_time + float(r['expires_in'])
            jdata = utils.load_json(self.jfile)
            jdata.update({'baidu': self.jdata})
            utils.write_json(self.jfile, jdata)

    def get_access_token(self):
        self.update_access_token()
        return self.jdata['access_token']

    def create(self, json):
        url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/eb-instant?access_token=" \
            + self.get_access_token()
        r = httpx.request("POST", url, headers=self.headers, json=json)
        return r.json()

class Chat():
    def __init__(self):
        ...
