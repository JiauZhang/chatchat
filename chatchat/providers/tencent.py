from chatchat.client import BaseClient

class TencentClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'tencent',
            'https://api.hunyuan.cloud.tencent.com/v1',
            client_kwargs=client_kwargs, model=model, instruction=instruction,
        )
