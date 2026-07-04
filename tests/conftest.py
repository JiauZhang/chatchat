"""Set dummy API keys for all providers so tests can run without real config."""
import os

# Set dummy env vars for all built-in providers to avoid ConfigError
_PROVIDERS = [
    'agnes', 'alibaba', 'baidu', 'deepseek', 'google', 'tencent',
    'xunfei', 'zhipu', 'openrouter',
]

for p in _PROVIDERS:
    key = f'CHATCHAT_{p.upper()}_API_KEY'
    if key not in os.environ:
        os.environ[key] = 'test-dummy-key'