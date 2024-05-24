import argparse

def parse_config(args):
    print(args)

parser = argparse.ArgumentParser()
subparser = parser.add_subparsers()

config_parser = subparser.add_parser('config', help='config platform secret key')
config_parser.add_argument('--list', action='store_true')
config_parser.set_defaults(parser=parse_config)

args = parser.parse_args()

def main():
    args.parser(args)

if __name__ == '__main__':
    main()
