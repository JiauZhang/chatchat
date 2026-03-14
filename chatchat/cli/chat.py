from chatchat.client import Client

def parse_config(args):
    if args.params:
        provider, model = args.params
        llm = Client(provider, model=model, http_options={
                'proxy': args.proxy, 'timeout': args.timeout,
            }
        )
        generation_options = {'stream': True, 'thinking': args.thinking}

        while True:
            prompt = input("user> ")
            if prompt == '/exit':
                exit()
            response = llm.chat(prompt, generation_options=generation_options)
            print('assistant> ', end='')
            for chunk in response:
                print(chunk, end="", flush=True)
            print()

def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with LLM')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None)
    config_parser.add_argument('--timeout', type=float, default=None)
    config_parser.add_argument('--thinking', action='store_true')
    config_parser.set_defaults(parser=parse_config)
