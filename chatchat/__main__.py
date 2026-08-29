import argparse
import asyncio
from chatchat import __version__
from chatchat.cli.config import register as register_config
from chatchat.cli.run import register as register_run

parser = argparse.ArgumentParser()
parser.add_argument(
    '-V', '--version',
    action='version',
    version=f'%(prog)s {__version__}',
)
parser.set_defaults(handler=None)
subparser = parser.add_subparsers()

register_config(subparser)
register_run(subparser)


def main():
    args = parser.parse_args()
    if args.handler:
        if asyncio.iscoroutinefunction(args.handler):
            asyncio.run(args.handler(args))
        else:
            args.handler(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
