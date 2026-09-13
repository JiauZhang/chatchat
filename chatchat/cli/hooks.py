import os

from chatchat.hooks.settings import get_all_hooks


def parse_config(args):
    hooks = get_all_hooks(os.getcwd())
    if not hooks:
        print('no hooks configured')
        return
    for h in hooks:
        print(f'[{h.source}] {h.event} matcher={h.matcher!r} '
              f'type={h.config.type} cmd={h.config.command or h.config.prompt or h.config.url!r}')


def cli_hooks(subparser):
    p = subparser.add_parser('hooks', help='List configured hooks from settings files')
    p.add_argument('target', type=str, nargs='?')
    p.set_defaults(parser=parse_config)
