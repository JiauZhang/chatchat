"""Set dummy API keys for all providers so tests can run without real config."""
import os
import pytest


@pytest.fixture(autouse=True)
def _cleanup_globals():
    """每个测试前清理全局状态。"""
    pass

# Set dummy env vars for all built-in providers to avoid ConfigError
_PROVIDERS = [
    'agnes', 'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu', 'openrouter',
]

for p in _PROVIDERS:
    key = f'CHATCHAT_{p.upper()}_API_KEY'
    if key not in os.environ:
        os.environ[key] = 'test-dummy-key'