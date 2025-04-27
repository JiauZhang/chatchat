from importlib import import_module
from chatchat.vendor import __vendor_info__

def parse_config(args):
    if args.params:
        vendor, model = args.params

        if vendor not in __vendor_info__:
            print(f'Vendor `{vendor}` is NOT supported!')
            print(f'Current supported vendors:\n    {list(__vendor_info__.keys())}')
            exit(-1)

        module = import_module(f'chatchat.{vendor}')
        chat = module.Chat(model=model, client_kwargs={'proxy': args.proxy})

        while True:
            prompt = input("user> ")
            if prompt == '\x04': # Ctrl+D
                exit()
            response = chat.chat(prompt)
            text = response if response.text is None else response.text
            print(f'assistant> {text}')

def cli_chat(subparser):
    config_parser = subparser.add_parser('run', help='Chat with AI')
    config_parser.add_argument('params', type=str, nargs=2)
    config_parser.add_argument('--proxy', type=str, default=None, required=False)
    config_parser.set_defaults(parser=parse_config)
