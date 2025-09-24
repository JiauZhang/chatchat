from chatchat.base import Base

class XunfeiClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'xunfei',
            'https://spark-api-open.xf-yun.com/v1',
            client_kwargs=client_kwargs, model=model,
        )
