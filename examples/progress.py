import argparse
import random
from chatchat.agent import Agent, SubAgent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=None)
args = parser.parse_args()

http_options = {'timeout': args.timeout or 30}


@tool(
    name='search_web', description='search information on the web',
    parameters={
        'type': 'object',
        'properties': {'query': {'type': 'string', 'description': 'search keywords'}},
        'required': ['query'],
    },
)
def search_web(query, on_step=None):
    if on_step:
        on_step(content=f'searching "{query}"...')
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    if on_step:
        on_step(content=f'found {len(results)} results')
    return '\n'.join(results)


@tool(
    name='summarize', description='summarize a text',
    parameters={
        'type': 'object',
        'properties': {'text': {'type': 'string', 'description': 'text to summarize'}},
        'required': ['text'],
    },
)
def summarize(text, on_step=None):
    if on_step:
        on_step(content='summarizing...')
    summary = f'Summary: {text[:50]}...'
    if on_step:
        on_step(content='summary ready')
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
def save_file(path, content, on_step=None):
    if on_step:
        on_step(content=f'writing to {path}...')
    raise PermissionError(f'no write permission for {path}')


def handle_start(evt: Progress):
    tag = evt.type.value
    evt_agent = evt.name or 'agent'
    if evt.type == ProgressType.TOOL_START:
        msg = f'calling "{evt_agent}"'
    else:
        msg = tag
    print(f'  [{tag:>12} {evt_agent:>10}] {msg}')


def handle_step(evt: Progress):
    tag = evt.type.value
    evt_agent = evt.name or 'agent'
    if evt.type == ProgressType.TOOL_STEP:
        msg = evt.content
    elif evt.step:
        msg = f'tool round {evt.step} complete, processing results'
    else:
        msg = tag
    print(f'  [{tag:>12} {evt_agent:>10}] {msg}')


def handle_end(evt: Progress):
    tag = evt.type.value
    evt_agent = evt.name or 'agent'
    if evt.type == ProgressType.TOOL_END:
        msg = f'"{evt_agent}" done'
    else:
        msg = tag
    print(f'  [{tag:>12} {evt_agent:>10}] {msg}')


def handle_error(evt: Progress):
    tag = evt.type.value
    evt_agent = evt.name or 'agent'
    if evt.type == ProgressType.TOOL_ERROR:
        msg = f'"{evt_agent}" failed: {evt.content}'
    else:
        msg = f'agent error: {evt.content}'
    print(f'  [{tag:>12} {evt_agent:>10}] {msg}')


researcher = SubAgent(
    name='researcher', description='search and summarize information',
    provider=args.provider, model=args.model,
    http_options=http_options, stream=False,
    tools=[search_web, summarize],
)
researcher.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)

supervisor = Agent(
    provider=args.provider, model=args.model,
    http_options=http_options, stream=False,
    instruction=(
        'You are a supervisor. You have a "researcher" assistant who can search and summarize.'
        ' You also have "save_file" and "search_web" tools.\n'
        'When given a task: delegate to "researcher" first, then try to save the result with "save_file",'
        ' and finally report what happened.'
    ),
    tools=[save_file, researcher],
)
supervisor.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)
result = supervisor.chat('search AI news and summarize')
print(f'  result: {result[:100]}')

print('Done.')