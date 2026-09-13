import argparse
import asyncio

from chatchat.client import Client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', default='deepseek')
parser.add_argument('--model', default='deepseek-chat')
parser.add_argument('--thinking', action='store_true')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()


async def main():
    llm = Client(args.provider, model=args.model, thinking=args.thinking,
                 http_options={'timeout': args.timeout, 'proxy': args.proxy})

    print('1. completion mode')
    print(await llm.complete('Hi'))

    print('\n2. chat mode (输入 /exit 退出)')
    while True:
        prompt = input('user> ')
        if prompt == '/exit':
            break
        print('\nassistant>')
        print(await llm.chat(prompt))


if __name__ == '__main__':
    asyncio.run(main())