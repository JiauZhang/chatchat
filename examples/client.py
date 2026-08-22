import argparse, asyncio
from chatchat.client import ClientConfig, create_client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()

client = create_client(ClientConfig(
    provider=args.provider, model=args.model,
    http_options={'timeout': args.timeout},
))


async def main():
    print('streaming: ', end='')
    async for chunk in client.chat([{'role': 'user', 'content': 'Say hello in 3 words'}]):
        if chunk.choices:
            delta = chunk.choices[0].delta.content or ''
            print(delta, end='', flush=True)
    print()
    await client.close()


if __name__ == '__main__':
    asyncio.run(main())