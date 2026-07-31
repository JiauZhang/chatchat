import os, sys, argparse, random, subprocess
from chatchat.agent import Agent
from chatchat.tool import tool
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--non-streaming', action='store_true')
args = parser.parse_args()

http_options = {}
if args.timeout:
    http_options['timeout'] = args.timeout
if args.proxy:
    http_options['proxy'] = args.proxy


@tool(
    name='query_train_ticket', description='查询从一个城市到另一个城市的火车票数量',
    parameters={
        'type': 'object',
        'properties': {
            'from_city': {'type': 'string', 'description': '出发城市名称，例如 Shanghai'},
            'to_city': {'type': 'string', 'description': '到达城市名称，例如 Beijing'},
        },
        'required': ['from_city', 'to_city'],
    },
)
def query_train_ticket(from_city, to_city):
    return f'{from_city} 到 {to_city} 还有 {random.randint(1, 10)} 张票。'


@tool(
    name='query_ticket_price', description='查询从一个城市到另一个城市的票价',
    parameters={
        'type': 'object',
        'properties': {
            'from_city': {'type': 'string', 'description': '出发城市名称，例如 Beijing'},
            'to_city': {'type': 'string', 'description': '到达城市名称，例如 Nanjing'},
        },
        'required': ['from_city', 'to_city'],
    },
)
def query_ticket_price(from_city, to_city):
    return f'{from_city} 到 {to_city} 的票价是 {random.randint(100, 200)} 元。'


@tool(
    name='read_file', description='读取文件内容',
    parameters={
        'type': 'object',
        'properties': {
            'file_path': {'type': 'string', 'description': '文件的绝对或相对路径，例如 "./output.txt"'},
            'offset': {'type': 'integer', 'description': '起始行号，默认从0开始'},
            'num_lines': {'type': 'integer', 'description': '读取行数，默认读取500行'},
        },
        'required': ['file_path'],
    },
)
def read_file(file_path, offset=0, num_lines=500):
    try:
        read_file._emit('tool:step', {'content': f'正在打开文件 {file_path}...'})
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        total_lines = len(lines)

        read_file._emit('tool:step', {'content': f'文件共 {total_lines} 行，准备读取偏移 {offset} 行起，共 {num_lines} 行'})
        result = '\n'.join(f'{i} | {line}' for i, line in enumerate(lines[offset:offset + num_lines], start=offset))
        read_count = min(num_lines, total_lines - offset)
        if not result:
            result = '(文件为空或读取范围无内容)'

        read_file._emit('tool:step', {'content': f'读取完成，共 {read_count} 行'})
        return f'读取成功，共 {read_count} 行，总行数 {total_lines}：\n{result}'
    except FileNotFoundError:
        return f'错误：文件不存在 - {file_path}'
    except Exception as e:
        return f'读取文件失败：{str(e)}'


@tool(
    name='write_file', description='将文本内容写入指定路径的文件（会覆盖已有文件）',
    parameters={
        'type': 'object',
        'properties': {
            'file_path': {'type': 'string', 'description': '文件的绝对或相对路径，例如 "./output.txt"'},
            'content': {'type': 'string', 'description': '要写入文件的文本内容'},
        },
        'required': ['file_path', 'content'],
    },
)
def write_file(file_path, content):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'成功写入文件：{file_path} (共 {len(content)} 字符)'
    except Exception as e:
        return f'写入文件失败：{str(e)}'


@tool(
    name='execute_shell_command', description='执行一条 shell 命令并返回其标准输出和标准错误',
    parameters={
        'type': 'object',
        'properties': {
            'command': {'type': 'string', 'description': '要执行的 shell 命令，例如 "ls -l" 或 "echo hello"'},
        },
        'required': ['command'],
    },
)
def execute_shell_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout
        if result.stderr:
            output += '\n[STDERR]\n' + result.stderr
        if not output.strip():
            output = '(无输出)'
        return output.strip()
    except subprocess.TimeoutExpired:
        return '错误：命令执行超过30秒超时。'
    except Exception as e:
        return f'执行命令时发生异常：{str(e)}'


def handle_agent_start(event: Event):
    msg = event.data.get('message', '')
    print(f'[agent:start  {event.source:>10}] {msg}')


def handle_agent_step(event: Event):
    tcs = event.data.get('tool_calls', [])
    names = [tc['name'] for tc in tcs]
    step = event.data.get('step', '')
    print(f'[agent:step   {event.source:>10}] round {step} -> {names}')


def handle_agent_end(event: Event):
    content = event.data.get('content', '')
    print(f'[agent:end    {event.source:>10}] {content[:60]}...')


def handle_agent_error(event: Event):
    print(f'[agent:error  {event.source:>10}] error: {event.data.get("error", "")}')


def handle_tool_start(event: Event):
    name = event.data.get('name', '')
    args = event.data.get('arguments', {})
    print(f'[tool:start   {event.source:>10}] calling "{name}" with {args}')


def handle_tool_step(event: Event):
    content = event.data.get('content', '')
    if content:
        print(f'[tool:step    {event.source:>10}] {content}')


def handle_tool_end(event: Event):
    name = event.data.get('name', '')
    result = event.data.get('result', '')
    print(f'[tool:end     {event.source:>10}] "{name}" done: {str(result)[:50]}...')


def handle_tool_error(event: Event):
    print(f'[tool:error   {event.source:>10}] error: {event.data.get("error", "")}')


def handle_client_step(event: Event):
    delta = event.data.get('delta', {}).get('content', '')
    if delta:
        print(f'[client:step  {event.source:>10}] {delta[:30]}')


with EventBus() as bus:
    bus.subscribe('agent:start', handle_agent_start)
    bus.subscribe('agent:step', handle_agent_step)
    bus.subscribe('agent:end', handle_agent_end)
    bus.subscribe('agent:error', handle_agent_error)
    bus.subscribe('tool:start', handle_tool_start)
    bus.subscribe('tool:step', handle_tool_step)
    bus.subscribe('tool:end', handle_tool_end)
    bus.subscribe('tool:error', handle_tool_error)
    bus.subscribe('client:step', handle_client_step)

    agent = Agent(
        name='assistant',
        event_bus=bus,
        provider=args.provider, model=args.model, http_options=http_options,
        stream=not args.non_streaming,
        instruction='你是一个全能助手，可以查询火车票、读写文件、执行shell命令。遇到专业任务时，请检查可用技能。',
        tools=[query_train_ticket, query_ticket_price, read_file, write_file, execute_shell_command],
        skills=[os.path.join(os.path.dirname(__file__), 'skills')],
    )

    print('Enter /exit to quit, /clear to reset conversation.')

    while True:
        prompt = input('user> ')
        if prompt == '/exit':
            break
        if prompt == '/clear':
            agent.clear()
            print('Conversation cleared.\n')
            continue

        response = agent.chat(prompt)

        if agent.stream:
            chunks = []
            for chunk in response:
                chunks.append(chunk)
            bus.flush()
            print(f'assistant> {"".join(chunks)}')
        else:
            print(f'assistant> {response}')
        print()