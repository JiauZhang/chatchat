from chatchat.client import BaseClient

class GoogleClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'google',
            'https://generativelanguage.googleapis.com/v1beta/openai/v1',
            http_options=http_options, model=model, instruction=instruction,
        )
