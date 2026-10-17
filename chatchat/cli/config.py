import json

from chatchat.client import secret_file


def parse_config(args):
    if args.list:
        names = sorted(_config_names())
        print(f"configured profiles: {', '.join(names) if names else '(none)'}")
        print(f"config file: {secret_file()}")
    elif args.cfgs:
        cfg = args.cfgs.split("=")
        provider_key = cfg[0].split(".")
        usage = "Usage: chatchat config {profile}.{key}={value}"
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
                print(f"cannot read {path}: not valid JSON, leaving it alone")
                return
        entry = secret_data.get(provider)
        if not isinstance(entry, dict):
            entry = secret_data[provider] = {}
        entry[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(secret_data, indent=4, ensure_ascii=False) + "\n")
        print(f"{provider}.{key} saved to {path}")


def _config_names():
    path = secret_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return []
    return [k for k, v in data.items() if isinstance(v, dict)]


def cli_config(subparser):
    config_parser = subparser.add_parser("config", help="config provider settings")
    config_parser.add_argument("cfgs", type=str, nargs="?")
    config_parser.add_argument("--list", action="store_true")
    config_parser.set_defaults(parser=parse_config)
