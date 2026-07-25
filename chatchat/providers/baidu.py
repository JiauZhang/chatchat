from chatchat.client import BaseClient

class BaiduClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None, event_bus=None):
        http_options = http_options or {}
        super().__init__(
            'baidu',
            'https://qianfan.baidubce.com/v2',
            http_options=http_options, model=model, instruction=instruction, event_bus=event_bus,
        )
