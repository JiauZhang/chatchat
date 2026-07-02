import argparse
import random
from chatchat.agent import Agent, SubAgent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
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
    search_web._emit(ProgressType.TOOL_STEP, content=f'searching "{query}"...', name='search_web')
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    search_web._emit(ProgressType.TOOL_STEP, content=f'found {len(results)} results', name='search_web')
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
    summarize._emit(ProgressType.TOOL_STEP, content='summarizing...', name='summarize')
    summary = f'Summary: {text[:50]}...'
    summarize._emit(ProgressType.TOOL_STEP, content='summary ready', name='summarize')
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
    save_file._emit(ProgressType.TOOL_STEP, content=f'writing to {path}...', name='save_file')
    raise PermissionError(f'no write permission for {path}')

def handle_start(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.TOOL_START:
        msg = f'calling "{name}"'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_step(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.TOOL_STEP:
        msg = progress.content
    elif progress.step:
        msg = f'tool round {progress.step} complete, processing results'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_end(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.TOOL_END:
        msg = f'"{name}" done'
    else:
        msg = tag
    print(f'[{tag:<12} {name:>10}] {msg}')


def handle_error(progress: Progress):
    tag = progress.type.value
    name = progress.name or 'agent'
    if progress.type == ProgressType.TOOL_ERROR:
        msg = f'"{name}" failed: {progress.content}'
    else:
        msg = f'agent error: {progress.content}'
    print(f'[{tag:<12} {name:>10}] {msg}')


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
print(f'supervisor result: {result[:100]}')

print('Done.')