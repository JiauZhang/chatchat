from chatchat.base import Base

class TencentClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'tencent',
            'https://api.hunyuan.cloud.tencent.com/v1',
            client_kwargs=client_kwargs, model=model,
        )
