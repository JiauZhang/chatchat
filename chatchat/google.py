from chatchat.base import Base

class GoogleClient(Base):
    def __init__(self, model=None, client_kwargs={}):
        super().__init__(
            'google',
            'https://generativelanguage.googleapis.com/v1beta/openai/v1',
            client_kwargs=client_kwargs, model=model,
        )
