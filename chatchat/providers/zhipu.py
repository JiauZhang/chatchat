from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('zhipu')
class ZhipuClient(BaseClient):
    base_url = 'https://open.bigmodel.cn/api/paas/v4'
