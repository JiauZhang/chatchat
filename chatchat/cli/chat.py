def parse_chat(args):
    ...

def cli_chat(subparser):
    config_parser = subparser.add_parser('chat', help='chat in terminal')
    config_parser.set_defaults(parser=parse_chat)
