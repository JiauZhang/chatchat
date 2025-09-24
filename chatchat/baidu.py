from chatchat.base import Base

class BaiduClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'baidu',
            'https://qianfan.baidubce.com/v2',
            client_kwargs=client_kwargs, model=model,
        )
