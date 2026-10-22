import json

from chatchat.client import secret_file

TYPES = ("openai", "anthropic")
WRITE_FIELDS = ("api_key", "base_url", "type", "rpm")


def _mask(value):
    value = (value or "").strip()
    if not value:
        return ""
    return "****" if len(value) <= 10 else f"{value[:6]}****{value[-4:]}"


def _read(path):
    """The profiles, or None when the file cannot be understood — the writer
    must not clobber a file it failed to read."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        print(f"cannot read {path}: not valid JSON, leaving it alone")
        return None
    if not isinstance(data, dict):
        print(f"cannot read {path}: not a JSON object, leaving it alone")
        return None
    return data


def show_config():
    path = secret_file()
    data = _read(path) or {}
    print(f"config file: {path}")
    if path.exists() and (path.stat().st_mode & 0o077):
        print(f"  permissions: {path.stat().st_mode & 0o777:o} (a secret file should be 600)")
    entries = [(name, entry) for name, entry in data.items() if isinstance(entry, dict)]
    if not entries:
        print("(no profiles configured)")
        return
    width = max(len(name) for name, _ in entries)
    for name, entry in sorted(entries):
        fields = [f"type={entry.get('type', '-')}", f"base_url={entry.get('base_url', '-')}"]
        fields.append(f"api_key={_mask(entry.get('api_key')) or '-'}")
        if entry.get("rpm"):
            fields.append(f"rpm={entry['rpm']}")
        print(f"  {name:<{width}}  " + "  ".join(fields))


def is_write_request(args):
    return any(getattr(args, field, None) is not None for field in WRITE_FIELDS)


def _apply(args):
    provider = (args.provider or "").strip()
    if not provider:
        print("--provider names the profile to write")
        return 1
    updates = {}
    if args.api_key is not None:
        updates["api_key"] = args.api_key.strip()
    if args.base_url is not None:
        updates["base_url"] = args.base_url.strip()
    if args.type is not None:
        updates["type"] = args.type
    if args.rpm is not None:
        if args.rpm < 1:
            print("--rpm must be a positive integer")
            return 1
        updates["rpm"] = args.rpm
    path = secret_file()
    data = _read(path)
    if data is None:
        return 1
    entry = data.get(provider)
    if not isinstance(entry, dict):
        entry = data[provider] = {}
    entry.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    shown = ", ".join(f"{key}={_mask(str(value)) if key == 'api_key' else value}" for key, value in updates.items())
    print(f"{provider}: {shown} saved to {path}")
    return 0


def parse_config(args):
    if not is_write_request(args):
        show_config()
        return 0
    return _apply(args)


def cli_config(subparser):
    config_parser = subparser.add_parser("config", help="show or set provider profiles")
    config_parser.add_argument("--provider", type=str, default=None, help="profile name to write")
    config_parser.add_argument("--api-key", type=str, default=None, help="API key for the profile")
    config_parser.add_argument("--base-url", type=str, default=None, help="API base URL")
    config_parser.add_argument("--type", type=str, default=None, choices=TYPES, help="protocol type")
    config_parser.add_argument("--rpm", type=int, default=None, help="requests per minute limit")
    config_parser.set_defaults(parser=parse_config)
    return config_parser
