from .version import __version__
from importlib import import_module

__vendors__ = [
    'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu',
]

def dynamic_import_client(vendor):
    if vendor not in __vendors__:
            print(f'vendor `{vendor}` is currently not supported!')
            print(f'supported vendors: {__vendors__}')
            exit(-1)
    client_module = import_module(f'chatchat.{vendor}')
    client_class = getattr(client_module, f'{vendor.capitalize()}Client')
    return client_class

class AI:
    def __init__(self, vendor, model=None, client_kwargs={}):
        client_class = dynamic_import_client(vendor)
        self.client = client_class(model=model, client_kwargs=client_kwargs)

    def complete(self, prompt, model=None, stream=False, generation_kwargs={}):
        return self.client.complete(
            prompt, model=model, stream=stream, generation_kwargs=generation_kwargs,
        )

    def clear(self):
        self.client.clear()

    def chat(self, text, model=None, history=None, stream=False, generation_kwargs={}):
        return self.client.chat(
            text, model=model, history=history, stream=stream,
            generation_kwargs=generation_kwargs,
        )