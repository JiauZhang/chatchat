from chatchat.client import BaseClient, ClientConfig
from chatchat.providers import register_provider


@register_provider('agnes')
class AgnesClient(BaseClient):
    def __init__(self, config: ClientConfig):
        http_options = config.http_options or {}
        domain = http_options.pop('domain', 'com')
        self.base_url = f'https://apihub.agnes-ai.{domain}/v1'
        super().__init__(config)