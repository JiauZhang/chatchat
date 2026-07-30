from chatchat.client import BaseClient


class AgnesClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None, event_bus=None):
        http_options = http_options or {}
        super().__init__(
            'agnes',
            'https://apihub.agnes-ai.cn/v1',
            http_options=http_options, model=model, instruction=instruction, event_bus=event_bus,
        )