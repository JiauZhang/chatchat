import os
import pytest


@pytest.fixture(autouse=True)
def _cleanup_globals():
    pass


_PROVIDERS = [
    'agnes', 'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu', 'openrouter',
]

for p in _PROVIDERS:
    key = f'CHATCHAT_{p.upper()}_API_KEY'
    if key not in os.environ:
        os.environ[key] = 'test-dummy-key'