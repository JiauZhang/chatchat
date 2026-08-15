import os, argparse, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler
from chatchat.agent import Agent, AgentConfig
from chatchat.tool import tool

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
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


scheduler = Scheduler()
agent = Agent(AgentConfig(
    name='assistant',
    provider=args.provider, model=args.model,
    http_options=http_options,
    instruction='You are a helpful assistant with write_file tool.',
    tools=[write_file],
), scheduler)
write_file.on_interact(handle_interact)

prompt = input('user> ')
response = agent.chat(prompt)
print(f'assistant> {response}')