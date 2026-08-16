from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('tencent')
class TencentClient(BaseClient):
    base_url = 'https://api.hunyuan.cloud.tencent.com/v1'
