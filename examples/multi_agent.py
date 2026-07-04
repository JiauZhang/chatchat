import os
import argparse
import random
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=120)
parser.add_argument('--non-streaming', action='store_true')
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
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    return '\n'.join(results)


@tool(
    name='save_file', description='save content to a file',
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
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f'saved to {path} ({len(content)} chars)'


@tool(
    name='current_time', description='get the current date and time',
    parameters={
        'type': 'object',
        'properties': {},
    },
)
def current_time():
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


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
        delta = progress.data.get('delta', {}).get('content', '')
        msg = delta[:30] if delta else tag
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


skills = [os.path.dirname(__file__)]

agent = Agent(
    name='supervisor',
    provider=args.provider, model=args.model,
    http_options=http_options,
    stream=not args.non_streaming,
    instruction=(
        'You are a supervisor agent. '
        'You have search_web, save_file, and current_time tools. '
        'For complex multi-step tasks, use the delegate tool to create '
        'specialized sub-agents for sub-tasks.\n\n'
        'Available skills: "weather" — use delegate(skill="weather") for weather queries.\n\n'
        'You can reuse a sub-agent by the same name to continue a previous task '
        '(its conversation history is preserved).'
    ),
    tools=[search_web, save_file, current_time],
    skills=skills,
)
agent.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)

print('Enter /exit to quit, /clear to reset conversation.')
print('Try: "research AI topics", "what is the weather?", "save results to a file", etc.')
print()

while True:
    prompt = input('user> ')
    if prompt == '/exit':
        break
    if prompt == '/clear':
        agent.clear()
        print('Conversation cleared.\n')
        continue

    response = agent.chat(prompt)

    if agent.stream:
        print('assistant> ', end='')
        for chunk in response:
            print(chunk, end='', flush=True)
        print()
    else:
        print(f'assistant> {response}')
    print()