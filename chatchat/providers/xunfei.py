from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('xunfei')
class XunfeiClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options=None, emit_fn=None):
        http_options = http_options or {}
        super().__init__(
            'https://spark-api-open.xf-yun.com/v1',
            http_options=http_options, model=model, instruction=instruction, emit_fn=emit_fn,
        )
