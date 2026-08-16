from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('baidu')
class BaiduClient(BaseClient):
    base_url = 'https://qianfan.baidubce.com/v2'
