from conippets import json
from chatchat import (
    base, alibaba, baidu, deepseek, tencent, xunfei, zhipu,
)

__vendor__ = (alibaba, baidu, deepseek, tencent, xunfei, zhipu)
__vendor_config__ = {
    vendor.__vendor__: vendor.__vendor_keys__ for vendor in __vendor__
}

def supported_vendors():
    print(f'Supported vendors:')
    for vendor, attrs in __vendor_config__.items():
        print(vendor)
        for attr in attrs:
            print(f'\t{attr}')

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
        if vendor not in __vendor_config__:
            print(f'Vendor <{vendor}> is currently NOT supported!')
            supported_vendors()
            return

        if key not in __vendor_config__[vendor]:
            print(f'Vendor <{vendor}> do NOT has secret key <{key}>!\nYou can set the following keys:')
            for key in __vendor_config__[vendor]:
                print(f'\t{key}')
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
