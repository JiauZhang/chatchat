from chatchat.client import BaseClient

class XunfeiClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        super().__init__(
            'xunfei',
            'https://spark-api-open.xf-yun.com/v1',
            http_options=http_options, model=model, instruction=instruction,
        )
