import os
from pathlib import Path
from conippets import json

__chatchat_home__ = Path(os.environ.get('CHATCHAT_HOME', str(Path.home() / '.chatchat')))
__chatchat_home__.mkdir(parents=True, exist_ok=True)
__config_file__ = str(__chatchat_home__ / 'chatchat.json')


def load_config(provider: str, key: str = 'api_key') -> str:
    if not os.path.exists(__config_file__):
        json.write(__config_file__, {})
    data = json.read(__config_file__)
    if provider not in data or key not in data[provider]:
        print('You need to configure your target provider first as bellow.')
        print(f'    chatchat config {provider}.{key}=YOUR_{key.upper()}')
        exit(-1)
    return data[provider][key]


def save_config(provider: str, key: str, value: str):
    data = json.read(__config_file__) if os.path.exists(__config_file__) else {}
    data.setdefault(provider, {})[key] = value
    json.write(__config_file__, data)
