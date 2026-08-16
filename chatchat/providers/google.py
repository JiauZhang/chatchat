from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('google')
class GoogleClient(BaseClient):
    base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/v1'
