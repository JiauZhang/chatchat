import json
from pathlib import Path

from chatchat.client import OFFICIAL_BASE_URLS, _default_secret_paths, secret_file


def _configured_names():
    names = set()
    for f in _default_secret_paths():
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
        except ValueError:
            continue
        if isinstance(data, dict):
            names |= {k for k, v in data.items() if isinstance(v, dict)}
    return names


def parse_config(args):
    if args.list:
        print(f'official providers: {", ".join(sorted(OFFICIAL_BASE_URLS))}')
        custom = sorted(_configured_names() - set(OFFICIAL_BASE_URLS))
        print(f'configured profiles: {", ".join(custom) if custom else "(none)"}')
    elif args.cfgs:
        cfg = args.cfgs.split('=')
        provider_key = cfg[0].split('.')
        usage = 'Usage: chatchat config {provider}.api_key=YOUR_API_KEY'
        if len(cfg) != 2 or len(provider_key) != 2 or not provider_key[0]:
            print(usage)
            return

        (provider, key), value = provider_key, cfg[1]
        path = secret_file()
        secret_data = {}
        if path.exists():
            try:
                secret_data = json.loads(path.read_text())
            except ValueError:
                print(f'cannot read {path}: not valid JSON, leaving it alone')
                return
        entry = secret_data.get(provider)
        if not isinstance(entry, dict):
            entry = secret_data[provider] = {}
        entry[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(secret_data, indent=4,
                                   ensure_ascii=False) + '\n')
        print(f'{provider}.{key} saved to {path}')


def cli_config(subparser):
    config_parser = subparser.add_parser('config', help='config provider secret key')
    config_parser.add_argument('cfgs', type=str, nargs='?')
    config_parser.add_argument('--list', action='store_true')
    config_parser.set_defaults(parser=parse_config)
