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
def search_web(query, on_progress=None):
    if on_progress:
        on_progress(Progress(type=ProgressType.TOOL_STEP, content=f'searching "{query}"...'))
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    if on_progress:
        on_progress(Progress(type=ProgressType.TOOL_STEP, content=f'found {len(results)} results'))
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
        on_progress(Progress(type=ProgressType.TOOL_STEP, content='summarizing...'))
    summary = f'Summary: {text[:50]}...'
    if on_progress:
        on_progress(Progress(type=ProgressType.TOOL_STEP, content='summary ready'))
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
        on_progress(Progress(type=ProgressType.TOOL_STEP, content=f'writing to {path}...'))
    raise PermissionError(f'no write permission for {path}')


def on_progress(evt: Progress):
    emoji = {
        ProgressType.AGENT_START: '\U0001f9e0',
        ProgressType.AGENT_STEP: '\U0001f463',
        ProgressType.AGENT_END: '\u2705',
        ProgressType.AGENT_ERROR: '\u274c',
        ProgressType.TOOL_START: '\U0001f527',
        ProgressType.TOOL_END: '\u2705',
        ProgressType.TOOL_ERROR: '\u274c',
        ProgressType.TOOL_STEP: '\u2139\ufe0f',
    }.get(evt.type, '  ')
    if evt.type == ProgressType.TOOL_START:
        msg = f'calling "{evt.tool_name}"'
    elif evt.type == ProgressType.TOOL_END:
        msg = f'"{evt.tool_name}" done'
    elif evt.type == ProgressType.AGENT_STEP:
        msg = f'tool round {evt.step} complete, processing results'
    elif evt.type == ProgressType.TOOL_ERROR:
        msg = f'"{evt.tool_name}" failed: {evt.content}'
    elif evt.type == ProgressType.AGENT_ERROR:
        msg = f'agents error: {evt.content}'
    else:
        msg = evt.content or evt.type.value
    agent = evt.agent or 'agent'
    print(f'  [{emoji} {agent:>10}] {msg}')


researcher = SubAgent(
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