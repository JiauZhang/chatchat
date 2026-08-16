from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('openrouter')
class OpenrouterClient(BaseClient):
    base_url = 'https://openrouter.ai/api/v1'
