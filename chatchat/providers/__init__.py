__providers__ = {}


def register_provider(name):
    def decorator(client_class):
        client_class.provider = name
        __providers__[name] = client_class
        return client_class
    return decorator