from chatchat.client import BaseClient
from chatchat.providers import register_provider

@register_provider('agnes')
class AgnesClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        domain = (http_options or {}).get('domain', 'com')
        super().__init__(
            'agnes',
            f'https://apihub.agnes-ai.{domain}/v1', model=model,
            http_options=http_options, instruction=instruction,
        )