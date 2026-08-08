from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('agnes')
class AgnesClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None, emit_fn=None):
        http_options = http_options or {}
        domain = http_options.pop('domain', 'com')
        super().__init__(
            f'https://apihub.agnes-ai.{domain}/v1',
            http_options=http_options, model=model, instruction=instruction, emit_fn=emit_fn,
        )