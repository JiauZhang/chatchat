import argparse, random, sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agents.agent import Agent, AgentConfig, create_agent
from chatchat.core.runtime import Runtime
from chatchat.tools.base import tool, ToolContext

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


runtime = Runtime()
for t in (search_web, summarize, save_file):
    runtime.registry.register(t)

for topic in ['lifecycle:agent:start', 'lifecycle:agent:step', 'lifecycle:agent:end', 'lifecycle:agent:error',
              'lifecycle:tool:start', 'lifecycle:tool:step', 'lifecycle:tool:end', 'lifecycle:tool:error']:
    runtime.subscribe(topic, handle_event)

agent = create_agent(AgentConfig(
    provider=args.provider, model=args.model,
    http_options=http_options,
    instruction=(
        'You are a supervisor. Search, summarize, and save to a file.'
    ),
    tools=['search_web', 'summarize', 'save_file'],
), runtime=runtime)


async def _ask(agent, text):
    from chatchat.core.ids import make_id
    return await runtime.request(
        source=make_id(), target_id=agent.id,
        topic=f'entity:{agent.kind}:{agent.id}:text', data=text,
        timeout=args.timeout,
    )


async def main():
    result = await _ask(agent, 'search AI news and summarize')
    print(f'\nsupervisor result: {result[:100]}')
    await agent.stop()
    await runtime.shutdown()
    print('Done.')


if __name__ == '__main__':
    asyncio.run(main())