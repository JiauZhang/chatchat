from chatchat import AI

def parse_config(args):
    if args.params:
        vendor, model = args.params
        ai = AI(vendor, model=model, client_kwargs={'proxy': args.proxy})

        while True:
            prompt = input("user> ")
            if prompt == '\x04': # Ctrl+D
                exit()
            response = ai.chat(prompt)
            text = response if response.text is None else response.text
            print(f'assistant> {text}')

def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with AI')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None)
    config_parser.set_defaults(parser=parse_config)
