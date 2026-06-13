from chatchat.client import BaseClient

class OpenrouterClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        super().__init__(
            'openrouter',
            'https://openrouter.ai/api/v1',
            http_options=http_options, model=model, instruction=instruction,
        )

        self._reasoning_content_key = 'reasoning'
