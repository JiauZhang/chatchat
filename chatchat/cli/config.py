from conippets import json
from chatchat import base, __vendors__

def parse_config(args):
    if args.list:
        print(f'supported vendors: {__vendors__}')
    elif args.cfgs:
        cfg = args.cfgs.split('=')
        vendor_key = cfg[0].split('.')
        usage = 'Usage: chatchat config {vendor}.api_key=YOUR_API_KEY'
        if len(cfg) != 2 or len(vendor_key) != 2:
            print(usage)
            return

        (vendor, key), value = vendor_key, cfg[1]
        if vendor not in __vendors__:
            print(f'vendor `{vendor}` is currently NOT supported!')
            print(f'supported vendors: {__vendors__}')
            return

        secret_file = base.__secret_file__
        secret_data = json.read(secret_file)

        if vendor in secret_data:
            secret_data[vendor][key] = value
        else:
            secret_data[vendor] = {key: value}
        json.write(secret_file, secret_data)

def cli_config(subparser):
    config_parser = subparser.add_parser('config', help='config vendor secret key')
    config_parser.add_argument('cfgs', type=str, nargs='?')
    config_parser.add_argument('--list', action='store_true')
    config_parser.set_defaults(parser=parse_config)
