from chatchat.client import ClientConfig, create_client


async def parse_config(args):
    if args.params:
        provider, model = args.params
        llm = create_client(ClientConfig(
            provider=provider, model=model,
            http_options={'proxy': args.proxy, 'timeout': args.timeout},
        ))

        try:
            while True:
                prompt = input("user> ")
                if prompt == '/exit':
                    break

                new_messages = [{'role': 'user', 'content': prompt}]
                print('assistant> ', end='')
                async for chunk in llm.chat(new_messages, thinking=args.thinking):
                    if chunk.choices:
                        print(chunk.choices[0].delta.content or '', end='', flush=True)
                print()
        finally:
            await llm.close()


def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with LLM')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None)
    config_parser.add_argument('--timeout', type=float, default=None)
    config_parser.add_argument('--thinking', action='store_true')
    config_parser.set_defaults(parser=parse_config)