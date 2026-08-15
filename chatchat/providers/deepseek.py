from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('deepseek')
class DeepseekClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        super().__init__(
            'https://api.deepseek.com',
            http_options=http_options, instruction=instruction,
        )
