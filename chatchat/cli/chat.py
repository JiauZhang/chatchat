from importlib import import_module
from chatchat.vendor import __vendor_info__

def parse_config(args):
    if args.cfgs:
        vendor, model = args.cfgs

        if vendor not in __vendor_info__:
            print(f'Vendor `{vendor}` is NOT supported!')
            print(f'Current supported vendors:\n    {list(__vendor_info__.keys())}')
            exit(-1)

        module = import_module(f'chatchat.{vendor}')
        chat = module.Chat(model=model)

        while True:
            prompt = input("user> ")
            assistant = chat.chat(prompt)
            print(f'assistant> {assistant}')

def cli_chat(subparser):
    config_parser = subparser.add_parser('with', help='chat with AI')
    config_parser.add_argument('cfgs', type=str, nargs=2)
    config_parser.set_defaults(parser=parse_config)
