from chatchat.base import Base

class ZhipuClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'zhipu',
            'https://open.bigmodel.cn/api/paas/v4',
            client_kwargs=client_kwargs, model=model,
        )
