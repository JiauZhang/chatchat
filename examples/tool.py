import argparse, random
from chatchat.tool import Tool, Tools
from chatchat.types import Progress, ProgressType
from chatchat.client import Client

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()

def search_impl(query):
    return '\n'.join([f'result {i} about {query}' for i in range(random.randint(1, 3))])

search = Tool(
    name='search', description='search the web',
    tool=search_impl,
    parameters={
        'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': 'search keywords'},
        }, 'required': ['query'],
    },
)

tools = Tools(search)

def on_start(p):
    if p.type == ProgressType.TOOL_START:
        print(f'tool start: {p.name} {p.data.get("arguments", {})}')

def on_end(p):
    if p.type == ProgressType.TOOL_END:
        result = p.data.get('result', '')
        print(f'tool end: {p.name} -> {str(result)[:50]}...')

search.on_start(on_start).on_end(on_end)

print(search(query='AI news'))

print()

client = Client(args.provider, args.model, http_options={'timeout': args.timeout})
result = client.chat(
    [{'role': 'user', 'content': 'search AI news'}],
    tools=tools, stream=False,
)
print(f'agent with manual tool: {result.choices[0].message.content[:80]}...')