from chatchat.client import BaseClient

class BaiduClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'baidu',
            'https://qianfan.baidubce.com/v2',
            client_kwargs=client_kwargs, model=model, instruction=instruction,
        )
