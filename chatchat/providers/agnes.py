from chatchat.client import BaseClient, ClientConfig
from chatchat.providers import register_provider


@register_provider('agnes')
class AgnesClient(BaseClient):
    def __init__(self, config: ClientConfig):
        domain = (config.http_options or {}).pop('domain', 'com')
        self.base_url = f'https://apihub.agnes-ai.{domain}/v1'
        super().__init__(config)