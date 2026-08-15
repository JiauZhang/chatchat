from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('openrouter')
class OpenrouterClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        super().__init__(
            'https://openrouter.ai/api/v1',
            http_options=http_options, model=model, instruction=instruction,
        )

        self._reasoning_content_key = 'reasoning'
