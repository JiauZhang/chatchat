import os, argparse, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agents.agent import Agent, AgentConfig, create_agent
from chatchat.core.runtime import Runtime
from chatchat.tools.base import tool

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=30)
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
    reply = write_file._ask(f'Write {len(content)} chars to "{path}"? (y/n)')
    if reply and reply.lower() in ('y', 'yes'):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'successfully wrote {path}'
    else:
        return 'operation cancelled'


def handle_interact(question, metadata):
    print(f'\n>>> {question}')
    return input('user>  ')


rt = Runtime()
rt.registry.register(write_file)

agent = create_agent(AgentConfig(
    provider=args.provider, model=args.model,
    http_options=http_options,
    instruction='You are a helpful assistant with write_file tool.',
    tools=['write_file'],
), runtime=rt)
write_file.on_interact(handle_interact)

async def _ask(agent, text):
    from chatchat.core.ids import make_id
    return await rt.request(
        source=make_id(), target_id=agent.id,
        topic=f'entity:{agent.kind}:{agent.id}:text', data=text,
        timeout=args.timeout,
    )


async def main():
    prompt = input('user> ')
    response = await _ask(agent, prompt)
    print(f'assistant> {response}')
    await agent.stop()
    await rt.shutdown()


if __name__ == '__main__':
    asyncio.run(main())