from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules

__providers__ = {}


def register_provider(name):
    def decorator(client_class):
        __providers__[name] = client_class
        return client_class
    return decorator


def _builtin_names():
    return {m.name for m in iter_modules([str(Path(__file__).parent)])}


def provider_names():
    return sorted(_builtin_names() | set(__providers__))


def get_provider(name):
    if name not in __providers__ and name in _builtin_names():
        import_module(f'{__name__}.{name}')
    return __providers__.get(name)
