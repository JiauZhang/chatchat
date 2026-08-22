import argparse, random
from chatchat.tool import Tool, Tools
from chatchat.client import ClientConfig, create_client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()


def search_impl(query):
    return '\n'.join([f'result {i} about {query}' for i in range(random.randint(1, 3))])


search = Tool(
    name='search', description='search the web',
    func=search_impl,
    parameters={
        'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': 'search keywords'},
        }, 'required': ['query'],
    },
)
tools = Tools(search)


async def main():
    print(await search(query='AI news'))
    print()

    client = create_client(ClientConfig(
        provider=args.provider, model=args.model,
        http_options={'timeout': args.timeout},
    ))
    parts = []
    async for chunk in client.chat(
        [{'role': 'user', 'content': 'search AI news'}],
        tools=tools,
    ):
        if chunk.choices:
            parts.append(chunk.choices[0].delta.content or '')
    await client.close()
    print(f'agent with manual tool: {"".join(parts)[:80]}...')


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())