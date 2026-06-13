from chatchat.client import BaseClient

class AlibabaClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        super().__init__(
            'alibaba',
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
            http_options=http_options, model=model, instruction=instruction,
        )
