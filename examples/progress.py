import argparse, random, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler, on_event, off_event
from chatchat.agent import Agent, AgentConfig
from chatchat.tool import tool
from chatchat.message import ID

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


def handle_event(topic, data):
    name = data.get('_source', '')
    if topic == 'tool:start':
        args = data.get('arguments', {})
        print(f'[{topic:<12} {name:>10}] calling "{name}" with {args}')
    elif topic == 'tool:step':
        content = data.get('content', '')
        print(f'[{topic:<12} {name:>10}] {content}')
    elif topic == 'tool:end':
        result = data.get('result', '')
        print(f'[{topic:<12} {name:>10}] done: {str(result)[:50]}...')
    elif topic == 'tool:error':
        args = data.get('arguments', {})
        err = data.get('error', '')
        print(f'[{topic:<12} {name:>10}] "{name}" failed: {err} args={args}')
    elif topic == 'agent:start':
        msg = data.get('message', '')
        print(f'[{topic:<12} {name:>10}] message: {msg}')
    elif topic == 'agent:step':
        tcs = data.get('tool_calls', [])
        names = [tc['name'] for tc in tcs]
        print(f'[{topic:<12} {name:>10}] tool round {data.get("step", "")} -> {names}')
    elif topic == 'agent:end':
        response = data.get('content', '')
        print(f'[{topic:<12} {name:>10}] response: {response[:60]}...')
    elif topic == 'agent:error':
        print(f'[{topic:<12} {name:>10}] error: {data.get("error", "")}')


scheduler = Scheduler()

for topic in ['agent:start', 'agent:step', 'agent:end', 'agent:error',
              'tool:start', 'tool:step', 'tool:end', 'tool:error']:
    on_event(topic, handle_event)

agent = Agent(AgentConfig(
    name='supervisor',
    provider=args.provider, model=args.model,
    http_options=http_options, stream=False,
    instruction=(
        'You are a supervisor. Search, summarize, and save to a file.'
    ),
    tools=[search_web, summarize, save_file],
), scheduler)

result = agent.chat('search AI news and summarize')
print(f'\nsupervisor result: {result[:100]}')

scheduler.shutdown()
print('Done.')