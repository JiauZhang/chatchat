import json
import argparse
import random
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
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


def handle_start(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.AGENT_START:
        msg = f'message: {progress.data.get("message", "")}'
    elif progress.type == ProgressType.TOOL_START:
        args = progress.data.get('arguments', {})
        msg = f'calling "{name}" with {args}'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_step(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.AGENT_STEP:
        tcs = progress.data.get('tool_calls', [])
        names = [tc['name'] for tc in tcs]
        msg = f'tool round {progress.step} -> {names}'
    elif progress.type == ProgressType.CLIENT_STEP:
        msg = progress.data.get('delta', {}).get('content', '')[:30] or tag
    else:
        msg = progress.content or tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_end(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.AGENT_END:
        response = progress.data.get('response', '')
        msg = f'response: {response[:60]}...'
    elif progress.type == ProgressType.TOOL_END:
        result = progress.data.get('result', '')
        msg = f'"{name}" done: {str(result)[:50]}...'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_error(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    print(f'[{tag:<12} {name:>10}] error: {progress.content}')


agent = Agent(
    name='analyst',
    provider=args.provider, model=args.model,
    http_options=http_options, stream=False,
    instruction=(
        'You are a financial analyst. You have stock query and news query tools. '
        'For complex research tasks, delegate to sub-agents.'
    ),
    tools=[query_stock, query_news],
)
agent.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)

result = agent.chat('What is the current price of AAPL and TSLA?')
print(f'\nanalyst result: {result}\n')

state = agent.state_dict()
with open('_agent_state.json', 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

with open('_agent_state.json', 'r', encoding='utf-8') as f:
    restored_state = json.load(f)

new_agent = Agent.from_state_dict(restored_state, tools=[query_stock, query_news])
new_agent.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)

result = new_agent.chat('What about GOOG?')
print(f'\nrestored agent result: {result}\n')

import os
os.remove('_agent_state.json')