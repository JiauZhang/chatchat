from chatchat.client import BaseClient

class AlibabaClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'alibaba',
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
            client_kwargs=client_kwargs, model=model, instruction=instruction,
        )
