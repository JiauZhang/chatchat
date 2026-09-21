from chatchat.client import BaseClient
from chatchat.providers import register_provider
from conippets import json

@register_provider('zhipu')
class ZhipuClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'zhipu',
            'https://open.bigmodel.cn/api/paas/v4',
            http_options=http_options, model=model, instruction=instruction,
        )
