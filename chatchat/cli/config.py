import os, argparse, pathlib, json
from chatchat.base import Base

__platform_config__ = {
    'alibaba': ['api_key'],
    'baidu': ['api_key', 'secret_key'],
    'tencent': ['secret_id', 'secret_key'],
    'xunfei': ['app_id', 'api_key', 'api_secret'],
    'deepseek': ['api_key'],
}

def supported_platforms():
    print(f'Supported platforms:')
    for plat, attrs in __platform_config__.items():
        print(plat)
        for attr in attrs:
            print(f'\t{attr}')

def parse_config(args):
    if args.list:
        supported_platforms()
    elif args.cfgs:
        cfg = args.cfgs.split('.')
        usage = 'Usage: chatchat config platform.key=value'
        if len(cfg) != 2:
            print(usage)
            return

        plat = cfg[0]
        if plat not in __platform_config__:
            print(f'Platform <{plat}> is currently NOT supported!')
            supported_platforms()
            return

        kv = cfg[1].split('=')
        if len(kv) != 2:
            print(usage)
            return
        key, value = kv

        if key not in __platform_config__[plat]:
            print(f'Platform <{plat}> do NOT has secret key <{key}>!\nYou can set the following keys:')
            for key in __platform_config__[plat]:
                print(f'\t{key}')
            return

        util = Base()
        dot_filename = util.secret_file
        dot_content = util.secret_data

        if plat in dot_content:
            dot_content[plat][key] = value
        else:
            dot_content[plat] = {key: value}
        util.write_json(dot_filename, dot_content)

def cli_config(subparser):
    config_parser = subparser.add_parser('config', help='config platform secret key')
    config_parser.add_argument('cfgs', type=str, nargs='?')
    config_parser.add_argument('--list', action='store_true')
    config_parser.set_defaults(parser=parse_config)
