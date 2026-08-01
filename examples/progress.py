import argparse
import random
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=30)
args = parser.parse_args()

http_options = {'timeout': args.timeout}


@tool(
    name='search_web', description='search information on the web',
    parameters={
        'type': 'object',
        'properties': {'query': {'type': 'string', 'description': 'search keywords'}},
        'required': ['query'],
    },
)
def search_web(query):
    search_web._emit('tool:step', {'content': f'searching "{query}"...', 'name': 'search_web'})
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    search_web._emit('tool:step', {'content': f'found {len(results)} results', 'name': 'search_web'})
    return '\n'.join(results)


@tool(
    name='summarize', description='summarize a text',
    parameters={
        'type': 'object',
        'properties': {'text': {'type': 'string', 'description': 'text to summarize'}},
        'required': ['text'],
    },
)
def summarize(text):
    summarize._emit('tool:step', {'content': 'summarizing...', 'name': 'summarize'})
    summary = f'Summary: {text[:50]}...'
    summarize._emit('tool:step', {'content': 'summary ready', 'name': 'summarize'})
    return summary


@tool(
    name='save_file', description='save content to a file (will fail due to permission)',
    parameters={
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description': 'file path'},
            'content': {'type': 'string', 'description': 'content to write'},
        },
        'required': ['path', 'content'],
    },
)
def save_file(path, content):
    save_file._emit('tool:step', {'content': f'writing to {path}...', 'name': 'save_file'})
    raise PermissionError(f'no write permission for {path}')


def handle_start(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'tool:start':
        args = event.data.get('arguments', {})
        msg = f'calling "{name}" with {args}'
    elif event.topic == 'agent:start':
        msg = f'message: {event.data.get("message", "")}'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_step(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'tool:step':
        msg = event.data.get('content', '')
    elif event.topic == 'client:step':
        delta = event.data.get('delta', {})
        tcs = delta.get('tool_calls', [])
        if tcs:
            msg = f'tool call delta: {[tc["name"] for tc in tcs]}'
        elif delta.get('content'):
            msg = f'content chunk: {delta["content"][:30]}...'
        else:
            msg = tag
    elif event.topic == 'agent:step':
        tcs = event.data.get('tool_calls', [])
        names = [tc['name'] for tc in tcs]
        msg = f'tool round {event.data.get("step", "")} -> {names}'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_end(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'tool:end':
        result = event.data.get('result', '')
        msg = f'"{name}" done: {str(result)[:50]}...'
    elif event.topic == 'agent:end':
        response = event.data.get('content', '')
        msg = f'response: {response[:60]}...'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_error(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'tool:error':
        args = event.data.get('arguments', {})
        msg = f'"{name}" failed: {event.data.get("error", "")} args={args}'
    else:
        msg = f'{name} error: {event.data.get("error", "")}'
    print(f'[{tag:<12} {name:>10}] {msg}')


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
        name='supervisor',
        event_bus=bus,
        provider=args.provider, model=args.model,
        http_options=http_options, stream=False,
        instruction=(
            'You are a supervisor. You have web search and summarization tools.'
            ' When given a task: search, summarize the results, then save to a file.'
        ),
        tools=[search_web, summarize, save_file],
    )
    result = agent.chat('search AI news and summarize')
    print(f'supervisor result: {result[:100]}')

    print('Done.')