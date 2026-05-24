from chatchat.providers import __providers__
from chatchat.config import save_config

def parse_config(args):
    if args.list:
        print(f'supported providers: {__providers__}')
    elif args.cfgs:
        cfg = args.cfgs.split('=')
        provider_key = cfg[0].split('.')
        usage = 'Usage: chatchat config {provider}.api_key=YOUR_API_KEY'
        if len(cfg) != 2 or len(provider_key) != 2:
            print(usage)
            return

        (provider, key), value = provider_key, cfg[1]
        if provider not in __providers__:
            print(f'provider `{provider}` is currently NOT supported!')
            print(f'supported providers: {__providers__}')
            return

        save_config(provider, key, value)

def cli_config(subparser):
    config_parser = subparser.add_parser('config', help='config provider secret key')
    config_parser.add_argument('cfgs', type=str, nargs='?')
    config_parser.add_argument('--list', action='store_true')
    config_parser.set_defaults(parser=parse_config)
