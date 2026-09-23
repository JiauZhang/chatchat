import asyncio

from chatchat.core.thinking import (LEVELS, MODES, Thinking)

from chatchat.client import Client


async def _loop(client):
    while True:
        prompt = input("user> ")
        if prompt == '/exit':
            break
        print('assistant>', end='', flush=True)
        print('\n' + await client.chat(prompt))


def parse_config(args):
    if args.params:
        provider, model = args.params
        client = Client(provider, model=model,
                        thinking=Thinking(mode=args.thinking,
                                          budget=args.thinking_budget,
                                          effort=args.effort),
                        http_options={'proxy': args.proxy,
                                      'timeout': args.timeout})
        asyncio.run(_loop(client))


def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with LLM')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None)
    config_parser.add_argument('--timeout', type=float, default=None)
    config_parser.add_argument('--thinking', choices=MODES, default='on')
    config_parser.add_argument('--thinking-budget', type=int, default=0)
    config_parser.add_argument('--effort', choices=LEVELS, default='')
    config_parser.set_defaults(parser=parse_config)