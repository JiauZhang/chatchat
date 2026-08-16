from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('alibaba')
class AlibabaClient(BaseClient):
    base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
