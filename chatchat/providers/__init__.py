__providers__ = [
    'agnes', 'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu', 'openrouter',
]

__custom_providers__ = {}


def register_provider(name):
    def decorator(client_class):
        __custom_providers__[name] = client_class
        return client_class
    return decorator