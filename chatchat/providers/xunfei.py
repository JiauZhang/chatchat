from chatchat.client import BaseClient

class XunfeiClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'xunfei',
            'https://spark-api-open.xf-yun.com/v1',
            client_kwargs=client_kwargs, model=model, instruction=instruction,
        )
