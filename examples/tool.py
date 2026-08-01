import argparse, random
from chatchat.tool import Tool, Tools
from chatchat.client import Client
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()


def search_impl(query):
    return '\n'.join([f'result {i} about {query}' for i in range(random.randint(1, 3))])


def on_start(event: Event):
    if event.topic == 'tool:start':
        print(f'tool start: {event.source} {event.data.get("arguments", {})}')


def on_end(event: Event):
    if event.topic == 'tool:end':
        result = event.data.get('result', '')
        print(f'tool end: {event.source} -> {str(result)[:50]}...')


with EventBus() as bus:
    search = Tool(
        name='search', description='search the web',
        tool=search_impl,
        parameters={
            'type': 'object', 'properties': {
                'query': {'type': 'string', 'description': 'search keywords'},
            }, 'required': ['query'],
        },
        event_bus=bus, source='search',
    )
    tools = Tools(search)

    bus.subscribe('tool:start', on_start)
    bus.subscribe('tool:end', on_end)

    print(search(query='AI news'))

    print()

    client = Client(args.provider, args.model, http_options={'timeout': args.timeout})
    result = client.chat(
        [{'role': 'user', 'content': 'search AI news'}],
        tools=tools, stream=False,
    )
    print(f'agent with manual tool: {result.choices[0].message.content[:80]}...')