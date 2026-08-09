import os, sys, argparse, random, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler
from chatchat.agent import Agent, AgentConfig
from chatchat.tool import Tool, tool


parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='deepseek')
parser.add_argument('--model', type=str, default='deepseek-v4-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

http_options = {}
if args.timeout:
    http_options['timeout'] = args.timeout
if args.proxy:
    http_options['proxy'] = args.proxy


@tool(name='query_train_ticket', description='query number of train tickets between cities',
      parameters={'type': 'object', 'properties': {
          'from_city': {'type': 'string', 'description': 'departure city'},
          'to_city': {'type': 'string', 'description': 'arrival city'},
      }, 'required': ['from_city', 'to_city']})
def query_train_ticket(from_city, to_city):
    return f'{from_city} to {to_city}: {random.randint(1, 10)} tickets left.'


@tool(name='query_ticket_price', description='query ticket price between cities',
      parameters={'type': 'object', 'properties': {
          'from_city': {'type': 'string', 'description': 'departure city'},
          'to_city': {'type': 'string', 'description': 'arrival city'},
      }, 'required': ['from_city', 'to_city']})
def query_ticket_price(from_city, to_city):
    return f'{from_city} to {to_city}: {random.randint(100, 200)} CNY.'


@tool(name='read_file', description='read file content',
      parameters={'type': 'object', 'properties': {
          'file_path': {'type': 'string', 'description': 'absolute or relative file path'},
          'offset': {'type': 'integer', 'description': 'starting line number'},
          'num_lines': {'type': 'integer', 'description': 'number of lines to read'},
      }, 'required': ['file_path']})
def read_file(file_path, offset=0, num_lines=500):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        total_lines = len(lines)
        read_count = min(num_lines, total_lines - offset)
        result = '\n'.join(f'{i} | {line}'
                           for i, line in enumerate(lines[offset:offset + num_lines], start=offset))
        if not result:
            result = '(empty file)'
        return f'read {read_count}/{total_lines} lines:\n{result}'
    except FileNotFoundError:
        return f'file not found: {file_path}'


@tool(name='write_file', description='write content to file (overwrites existing)',
      parameters={'type': 'object', 'properties': {
          'file_path': {'type': 'string', 'description': 'file path'},
          'content': {'type': 'string', 'description': 'content to write'},
      }, 'required': ['file_path', 'content']})
def write_file(file_path, content):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'wrote {len(content)} chars to {file_path}'
    except Exception as e:
        return f'write failed: {e}'


@tool(name='execute_shell_command', description='execute a shell command',
      parameters={'type': 'object', 'properties': {
          'command': {'type': 'string', 'description': 'shell command to execute'},
      }, 'required': ['command']})
def execute_shell_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout
        if result.stderr:
            output += '\n[STDERR]\n' + result.stderr
        return output.strip() or '(no output)'
    except subprocess.TimeoutExpired:
        return 'command timed out after 30s'


scheduler = Scheduler()
agent = Agent(AgentConfig(
    name='assistant',
    provider=args.provider, model=args.model, http_options=http_options,
    stream=True,
    instruction='You are a helpful assistant with tools for tickets, files, and shell commands.',
    tools=[query_train_ticket, query_ticket_price, read_file, write_file, execute_shell_command],
), scheduler)

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
    print(f'assistant> {response}')
    print()