from conippets import json
from chatchat import base
from chatchat.vendor import __vendor_info__

def supported_vendors():
    print(f'Supported vendors:')
    for vendor, attrs in __vendor_info__.items():
        print(vendor)
        for attr in attrs:
            print(f'    {attr}')

def parse_config(args):
    if args.list:
        supported_vendors()
    elif args.cfgs:
        cfg = args.cfgs.split('=')
        vendor_key = cfg[0].split('.')
        usage = 'Usage: chatchat config vendor.key=value'
        if len(cfg) != 2 or len(vendor_key) != 2:
            print(usage)
            return

        (vendor, key), value = vendor_key, cfg[1]
        if vendor not in __vendor_info__:
            print(f'Vendor <{vendor}> is currently NOT supported!')
            supported_vendors()
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
