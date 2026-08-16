from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('deepseek')
class DeepseekClient(BaseClient):
    base_url = 'https://api.deepseek.com'
