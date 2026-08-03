from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('agnes')
class AgnesClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None, event_bus=None):
        http_options = http_options or {}
        domain = http_options.pop('domain', 'com')
        super().__init__(
            f'https://apihub.agnes-ai.{domain}/v1',
            http_options=http_options, model=model, instruction=instruction, event_bus=event_bus,
        )