from chatchat.client import Client


def parse_config(args):
    if args.params:
        provider, model = args.params
        llm = Client(provider, model=model, http_options={
                'proxy': args.proxy, 'timeout': args.timeout,
            }
        )

        while True:
            prompt = input("user> ")
            if prompt == '/exit':
                exit()

            new_messages = [{'role': 'user', 'content': prompt}]
            stream = not args.non_streaming

            if stream:
                response = llm.chat(new_messages, stream=True, thinking=args.thinking)
                print('assistant> ', end='')
                for chunk in response:
                    print(chunk.choices[0].delta.content or '', end='', flush=True)
                print()
            else:
                response = llm.chat(new_messages, stream=False, thinking=args.thinking)
                print(f'assistant> {response.choices[0].message.content}')


def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with LLM')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None)
    config_parser.add_argument('--timeout', type=float, default=None)
    config_parser.add_argument('--thinking', action='store_true')
    config_parser.add_argument('--non-streaming', action='store_true')
    config_parser.set_defaults(parser=parse_config)