from chatchat.client import BaseClient

class ZhipuClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'zhipu',
            'https://open.bigmodel.cn/api/paas/v4',
            client_kwargs=client_kwargs, model=model, instruction=instruction,
        )
