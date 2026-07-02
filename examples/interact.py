import os, argparse
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.types import Progress, ProgressType

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.0-flash')
parser.add_argument('--timeout', type=int, default=30)
parser.add_argument('--non-streaming', action='store_true')
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
    write_file._emit(ProgressType.TOOL_STEP, content=f'ready to write {len(content)} chars to {path}', name='write_file')
    reply = write_file._ask(f'Write {len(content)} chars to "{path}"? (y/n)')
    if reply and reply.lower() in ('y', 'yes'):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        write_file._emit(ProgressType.TOOL_STEP, content=f'written {len(content)} chars to {path}', name='write_file')
        return f'successfully wrote {path}'
    else:
        write_file._emit(ProgressType.TOOL_STEP, content='cancelled by user', name='write_file')
        return 'operation cancelled'


agent = Agent(
    provider=args.provider, model=args.model,
    http_options=http_options, stream=not args.non_streaming,
    instruction='You are a helpful assistant with write_file tool.',
    tools=[write_file],
)


def handle_start(progress: Progress):
    tag = progress.type.value
    print(f'[{tag:<12} {progress.name or "agent":>10}] start')


def handle_step(progress: Progress):
    tag = progress.type.value
    print(f'[{tag:<12} {progress.name or "agent":>10}] {progress.content}')


def handle_end(progress: Progress):
    tag = progress.type.value
    print(f'[{tag:<12} {progress.name or "agent":>10}] end')


def handle_error(progress: Progress):
    tag = progress.type.value
    print(f'[{tag:<12} {progress.name or "agent":>10}] error: {progress.content}')


def handle_interact(question, metadata):
    print(f'\n>>> {question}')
    return input('user>  ')


agent.on_start(handle_start).on_step(handle_step).on_end(handle_end).on_error(handle_error)
write_file.on_interact(handle_interact)

prompt = input('user> ')
response = agent.chat(prompt)

if agent.stream:
    print('assistant> ', end='')
    for chunk in response:
        print(chunk, end='', flush=True)
    print()
else:
    print(f'assistant> {response}')