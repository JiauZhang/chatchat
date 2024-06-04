import argparse
from chatchat.cli.config import cli_config
from chatchat.cli.chat import cli_chat

parser = argparse.ArgumentParser()
parser.set_defaults(parser=None)
subparser = parser.add_subparsers()

cli_config(subparser)
cli_chat(subparser)

args = parser.parse_args()

def main():
    if args.parser:
        args.parser(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
