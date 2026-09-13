from chatchat.client import BaseClient

class DeepseekClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'deepseek',
            'https://api.deepseek.com', model=model,
            http_options=http_options, instruction=instruction,
        )
