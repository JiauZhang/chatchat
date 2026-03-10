from chatchat.client import BaseClient

class DeepseekClient(BaseClient):
    def __init__(self, model=None, instruction=None, client_kwargs={}):
        super().__init__(
            'deepseek',
            'https://api.deepseek.com', model=model,
            client_kwargs=client_kwargs, instruction=instruction,
        )
