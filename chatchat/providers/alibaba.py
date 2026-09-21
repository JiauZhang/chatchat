from chatchat.client import BaseClient
from chatchat.providers import register_provider

@register_provider('alibaba')
class AlibabaClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'alibaba',
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
            http_options=http_options, model=model, instruction=instruction,
        )
