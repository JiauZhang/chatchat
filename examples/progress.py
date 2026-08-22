import argparse, random, sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.tool import tool, ToolContext
from chatchat import get_runtime

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
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
def search_web(query, ctx: ToolContext = None):
    search_web.step(ctx, f'searching "{query}"...')
    results = [f'result {i} about {query}' for i in range(random.randint(1, 3))]
    search_web.step(ctx, f'found {len(results)} results')
    return '\n'.join(results)


@tool(
    name='summarize', description='summarize a text',
    parameters={
        'type': 'object',
        'properties': {'text': {'type': 'string', 'description': 'text to summarize'}},
        'required': ['text'],
    },
)
def summarize(text, ctx: ToolContext = None):
    summarize.step(ctx, 'summarizing...')
    summary = f'Summary: {text[:50]}...'
    summarize.step(ctx, 'summary ready')
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
def save_file(path, content, ctx: ToolContext = None):
    save_file.step(ctx, f'writing to {path}...')
    raise PermissionError(f'no write permission for {path}')


def handle_event(ev):
    name = ev.source
    topic = ev.topic
    data = ev.data
    if topic == 'lifecycle:tool:start':
        args = data.get('arguments', {})
        print(f'[{topic:<22} {name:>10}] calling "{name}" with {args}')
    elif topic == 'lifecycle:tool:step':
        content = data.get('content', '')
        print(f'[{topic:<22} {name:>10}] {content}')
    elif topic == 'lifecycle:tool:end':
        result = data.get('result', '')
        print(f'[{topic:<22} {name:>10}] done: {str(result)[:50]}...')
    elif topic == 'lifecycle:tool:error':
        args = data.get('arguments', {})
        err = data.get('error', '')
        print(f'[{topic:<22} {name:>10}] "{name}" failed: {err} args={args}')
    elif topic == 'lifecycle:agent:start':
        msg = data.get('message', '')
        print(f'[{topic:<22} {name:>10}] message: {msg}')
    elif topic == 'lifecycle:agent:step':
        tcs = data.get('tool_calls', [])
        names = [tc['name'] for tc in tcs]
        print(f'[{topic:<22} {name:>10}] tool round {data.get("step", "")} -> {names}')
    elif topic == 'lifecycle:agent:end':
        response = data.get('content', '')
        print(f'[{topic:<22} {name:>10}] response: {response[:60]}...')
    elif topic == 'lifecycle:agent:error':
        print(f'[{topic:<22} {name:>10}] error: {data.get("error", "")}')


runtime = get_runtime()

for topic in ['lifecycle:agent:start', 'lifecycle:agent:step', 'lifecycle:agent:end', 'lifecycle:agent:error',
              'lifecycle:tool:start', 'lifecycle:tool:step', 'lifecycle:tool:end', 'lifecycle:tool:error']:
    runtime.subscribe(topic, handle_event)

agent = create_agent(AgentConfig(
    name='supervisor',
    provider=args.provider, model=args.model,
    http_options=http_options,
    instruction=(
        'You are a supervisor. Search, summarize, and save to a file.'
    ),
    tools=[search_web, summarize, save_file],
))


async def main():
    result = await agent.chat('search AI news and summarize')
    print(f'\nsupervisor result: {result[:100]}')
    await agent.stop()
    runtime.shutdown()
    print('Done.')


if __name__ == '__main__':
    asyncio.run(main())