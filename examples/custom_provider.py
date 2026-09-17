"""Define and register a custom LLM provider.

1. 定义一个 BaseClient 子类，__init__ 签名保持 (model=None, instruction=None, http_options={})。
2. 用 @register_provider('myvendor') 注册。
3. 配置密钥: chatchat config myvendor.api_key=YOUR_KEY
   (或设置环境变量 CHATCHAT_MYVENDOR_API_KEY)。
4. 即可通过 Client('myvendor', model=...) 使用。
"""

import asyncio

from chatchat.client import BaseClient, Client
from chatchat.providers import register_provider


@register_provider('myvendor')
class MyVendorClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'myvendor',
            'https://api.myvendor.com/v1',
            model=model,
            instruction=instruction,
            http_options=http_options,
        )


async def main():
    llm = Client('myvendor', model='myvendor-chat', thinking=False)
    print(await llm.complete('Hi'))


if __name__ == '__main__':
    asyncio.run(main())
