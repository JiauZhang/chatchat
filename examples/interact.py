import os, argparse
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=30)
parser.add_argument('--non-streaming', action='store_true')
args = parser.parse_args()

http_options = {'timeout': args.timeout}


@tool(
    name='write_file', description='write text content to a file',
    parameters={
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'description': 'file path'},
            'content': {'type': 'string', 'description': 'content to write'},
        },
        'required': ['path', 'content'],
    },
)
def write_file(path, content):
    write_file._emit('tool:step', {'content': f'ready to write {len(content)} chars to {path}', 'name': 'write_file'})
    reply = write_file._ask(f'Write {len(content)} chars to "{path}"? (y/n)')
    if reply and reply.lower() in ('y', 'yes'):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        write_file._emit('tool:step', {'content': f'written {len(content)} chars to {path}', 'name': 'write_file'})
        return f'successfully wrote {path}'
    else:
        write_file._emit('tool:step', {'content': 'cancelled by user', 'name': 'write_file'})
        return 'operation cancelled'


def handle_start(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'agent:start':
        msg = f'message: {event.data.get("message", "")}'
    elif event.topic == 'tool:start':
        args = event.data.get('arguments', {})
        msg = f'tool args: {args}'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_step(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'client:step':
        delta = event.data.get('delta', {}).get('content', '')
        msg = delta if delta else tag
    else:
        msg = event.data.get('content', '') or tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_end(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    if event.topic == 'tool:end':
        result = event.data.get('result', '')
        msg = f'done: {result[:60]}...'
    elif event.topic == 'agent:end':
        response = event.data.get('content', '')
        msg = f'response: {response[:60]}...'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_error(event: Event):
    tag = event.topic
    name = event.source or 'agent'
    print(f'[{tag:<12} {name:>10}] error: {event.data.get("error", "")}')


def handle_interact(question, metadata):
    print(f'\n>>> {question}')
    return input('user>  ')


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
        event_bus=bus,
        provider=args.provider, model=args.model,
        http_options=http_options, stream=not args.non_streaming,
        instruction='You are a helpful assistant with write_file tool.',
        tools=[write_file],
    )
    write_file.on_interact(handle_interact)

    prompt = input('user> ')
    response = agent.chat(prompt)

    if agent.stream:
        print('assistant> ', end='')
        for chunk in response:
            print(chunk, end='', flush=True)
        print()
    else:
        print(f'assistant> {response}')