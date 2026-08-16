from chatchat.client import BaseClient
from chatchat.providers import register_provider


@register_provider('xunfei')
class XunfeiClient(BaseClient):
    base_url = 'https://spark-api-open.xf-yun.com/v1'
