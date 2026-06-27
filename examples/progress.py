import argparse
import random
from chatchat.agent import Agent, AgentTool
from chatchat.tool import tool
from chatchat.types import Progress

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
def search_web(query, on_progress=None):
    if on_progress:
        on_progress(Progress(type='progress', content=f'searching "{query}"...'))
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    if on_progress:
        on_progress(Progress(type='progress', content=f'found {len(results)} results'))
    return '\n'.join(results)


@tool(
    name='summarize', description='summarize a text',
    parameters={
        'type': 'object',
        'properties': {'text': {'type': 'string', 'description': 'text to summarize'}},
        'required': ['text'],
    },
)
def summarize(text, on_progress=None):
    if on_progress:
        on_progress(Progress(type='progress', content='summarizing...'))
    summary = f'Summary: {text[:50]}...'
    if on_progress:
        on_progress(Progress(type='progress', content='summary ready'))
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
def save_file(path, content, on_progress=None):
    if on_progress:
        on_progress(Progress(type='progress', content=f'writing to {path}...'))
    raise PermissionError(f'no write permission for {path}')


def on_progress(evt: Progress):
    emoji = {'thinking': '\U0001f9e0', 'step': '\U0001f463', 'tool_start': '\U0001f527',
             'tool_end': '\u2705', 'tool_error': '\u274c', 'progress': '\u2139\ufe0f',
             'complete': '\u2705'}.get(evt.type, '  ')
    if evt.type == 'tool_start':
        msg = f'calling "{evt.tool_name}"'
    elif evt.type == 'tool_end':
        msg = f'"{evt.tool_name}" done'
    elif evt.type == 'step':
        msg = f'tool round {evt.step} complete, processing results'
    elif evt.type == 'tool_error':
        msg = f'"{evt.tool_name}" failed: {evt.content}'
    else:
        msg = evt.content or evt.type
    agent = evt.agent or 'agent'
    print(f'  [{emoji} {agent:>10}] {msg}')


researcher = AgentTool(
    name='researcher', description='search and summarize information',
    provider=args.provider, model=args.model,
    http_options=http_options, stream=False,
    tools=[search_web, summarize],
)

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
result = supervisor.chat('search AI news and summarize', on_progress=on_progress)
print(f'  result: {result[:100]}')

print('Done.')