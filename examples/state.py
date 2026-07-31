import json
import argparse
import random
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=120)
args = parser.parse_args()

http_options = {'timeout': args.timeout}


@tool(
    name='query_stock', description='query current stock price by symbol',
    parameters={
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'description': 'stock symbol, e.g. AAPL, TSLA'},
        },
        'required': ['symbol'],
    },
)
def query_stock(symbol):
    prices = {'AAPL': 198.5, 'TSLA': 245.3, 'GOOG': 175.2, 'MSFT': 420.8}
    return f'{symbol} current price: ${prices.get(symbol.upper(), random.uniform(50, 500)):.2f}'


@tool(
    name='query_news', description='query recent news headlines',
    parameters={
        'type': 'object',
        'properties': {
            'topic': {'type': 'string', 'description': 'news topic'},
        },
        'required': ['topic'],
    },
)
def query_news(topic):
    headlines = [
        f'{topic}: Major breakthrough announced',
        f'{topic}: Market analysis shows growth trend',
        f'{topic}: New regulations impact industry',
    ]
    return '\n'.join(headlines)


def handle_start(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'agent:start':
        msg = f'message: {event.data.get("message", "")}'
    elif event.topic == 'tool:start':
        args = event.data.get('arguments', {})
        msg = f'calling "{name}" with {args}'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_step(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'agent:step':
        tcs = event.data.get('tool_calls', [])
        names = [tc['name'] for tc in tcs]
        msg = f'tool round {event.data.get("step", "")} -> {names}'
    elif event.topic == 'client:step':
        msg = event.data.get('delta', {}).get('content', '')[:30] or tag
    else:
        msg = event.data.get('content', '') or tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_end(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'agent:end':
        response = event.data.get('response', '')
        msg = f'response: {response[:60]}...'
    elif event.topic == 'tool:end':
        result = event.data.get('result', '')
        msg = f'"{name}" done: {str(result)[:50]}...'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_error(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    print(f'[{tag:<12} {name:>10}] error: {event.data.get("error", "")}')


with EventBus() as bus:
    bus.subscribe('agent:start', handle_start)
    bus.subscribe('agent:step', handle_step)
    bus.subscribe('agent:end', handle_end)
    bus.subscribe('agent:error', handle_error)
    bus.subscribe('tool:start', handle_start)
    bus.subscribe('tool:step', handle_step)
    bus.subscribe('tool:end', handle_end)
    bus.subscribe('tool:error', handle_error)
    bus.subscribe('client:step', handle_step)

    agent = Agent(
        name='analyst',
        event_bus=bus,
        provider=args.provider, model=args.model,
        http_options=http_options, stream=False,
        instruction=(
            'You are a financial analyst. You have stock query and news query tools. '
            'For complex research tasks, delegate to sub-agents.'
        ),
        tools=[query_stock, query_news],
    )

    result = agent.chat('What is the current price of AAPL and TSLA?')
    print(f'\nanalyst result: {result}\n')

    state = agent.state_dict()
    with open('_agent_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    with open('_agent_state.json', 'r', encoding='utf-8') as f:
        restored_state = json.load(f)

    new_agent = Agent.from_state_dict(restored_state, event_bus=bus, tools=[query_stock, query_news])

    result = new_agent.chat('What about GOOG?')
    print(f'\nrestored agent result: {result}\n')

    import os
    os.remove('_agent_state.json')