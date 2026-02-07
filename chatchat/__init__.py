from .version import __version__
from importlib import import_module

__providers__ = [
    'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu',
]

def dynamic_import_client(provider):
    if provider not in __providers__:
            print(f'provider `{provider}` is currently not supported!')
            print(f'supported providers: {__providers__}')
            exit(-1)
    client_module = import_module(f'chatchat.{provider}')
    client_class = getattr(client_module, f'{provider.capitalize()}Client')
    return client_class

class AI:
    def __init__(self, provider, model=None, instruction=None, client_kwargs={}):
        client_class = dynamic_import_client(provider)
        self.client = client_class(model=model, instruction=instruction, client_kwargs=client_kwargs)

    def complete(self, prompt, model=None, stream=False, generation_kwargs={}):
        return self.client.complete(
            prompt, model=model, stream=stream, generation_kwargs=generation_kwargs,
        )

    @property
    def history(self):
        return self.client.history

    @property
    def instruction(self):
         return self.client.instruction
    
    @instruction.setter
    def instruction(self, value):
         self.client.instruction = value

    def clear(self):
        self.client.clear()

    def chat(self, text, model=None, history=None, stream=False, generation_kwargs={}):
        return self.client.chat(
            text, model=model, history=history, stream=stream,
            generation_kwargs=generation_kwargs,
        )