from chatchat.client import BaseClient
from chatchat.providers import register_provider

@register_provider('deepseek')
class DeepseekClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'deepseek',
            'https://api.deepseek.com', model=model,
            http_options=http_options, instruction=instruction,
        )
