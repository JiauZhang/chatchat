from chatchat.client import BaseClient

class TencentClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'tencent',
            'https://api.hunyuan.cloud.tencent.com/v1',
            http_options=http_options, model=model, instruction=instruction,
        )
