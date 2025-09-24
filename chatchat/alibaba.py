from chatchat.base import Base

class AlibabaClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'alibaba',
            'https://dashscope.aliyuncs.com/compatible-mode/v1',
            client_kwargs=client_kwargs, model=model,
        )
