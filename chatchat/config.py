import os
import stat
from pathlib import Path
from conippets import json
from chatchat import ConfigError

__chatchat_home__ = Path(os.environ.get('CHATCHAT_HOME', str(Path.home() / '.chatchat')))
__chatchat_home__.mkdir(parents=True, exist_ok=True)
__config_file__ = str(__chatchat_home__ / 'chatchat.json')


def _ensure_file_permissions():
    if os.path.exists(__config_file__):
        os.chmod(__config_file__, stat.S_IRUSR | stat.S_IWUSR)


def load_config(provider: str, key: str = 'api_key') -> str:
    env_key = f'CHATCHAT_{provider.upper()}_{key.upper()}'
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value

    if not os.path.exists(__config_file__):
        json.write(__config_file__, {})
    _ensure_file_permissions()
    data = json.read(__config_file__)
    if provider not in data or key not in data[provider]:
        raise ConfigError(
            f'Provider "{provider}" is not configured. '
            f'Run: chatchat config {provider}.{key}=YOUR_{key.upper()}'
        )
    return data[provider][key]


def save_config(provider: str, key: str, value: str):
    data = json.read(__config_file__) if os.path.exists(__config_file__) else {}
    data.setdefault(provider, {})[key] = value
    json.write(__config_file__, data)
    _ensure_file_permissions()