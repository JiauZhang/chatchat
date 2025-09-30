from chatchat.base import Base

class DeepseekClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'deepseek',
            'https://api.deepseek.com', model=model,
            client_kwargs=client_kwargs,
        )
