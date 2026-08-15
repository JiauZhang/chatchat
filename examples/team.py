import os, sys, argparse, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler, enable_event_logging
from chatchat.team import Team, TeamConfig
from chatchat.message import Message, make_id
from chatchat.tool import tool
from chatchat.rate_limiter import set_rate_limits


parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--thinking', action='store_true', default=False)
args = parser.parse_args()

http_options = {}
if args.timeout:
    http_options['timeout'] = args.timeout
if args.proxy:
    http_options['proxy'] = args.proxy

set_rate_limits([
    {'provider': 'agnes', 'rpm': 20},
])


@tool(name='write_file', description='write content to a file',
      parameters={'type': 'object', 'properties': {
          'path': {'type': 'string', 'description': 'file path'},
          'content': {'type': 'string', 'description': 'content to write'},
      }, 'required': ['path', 'content']})
def write_file(path, content):
    write_file._emit('tool:step', {'content': f'writing {len(content)} chars to {path}'})
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f'wrote {len(content)} chars to {path}'
    except Exception as e:
        return f'write failed: {e}'


@tool(name='read_file', description='read file content',
      parameters={'type': 'object', 'properties': {
          'path': {'type': 'string', 'description': 'file path'},
      }, 'required': ['path']})
def read_file(path):
    read_file._emit('tool:step', {'content': f'reading {path}'})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        read_file._emit('tool:step', {'content': f'read {len(content)} chars from {path}'})
        return content
    except Exception as e:
        read_file._emit('tool:step', {'content': f'read failed: {e}'})
        return f'read failed: {e}'


scheduler = Scheduler()

enable_event_logging('client', 'tool', 'agent')

time.sleep(0.1)

team = Team(TeamConfig(
    name='lead',
    provider=args.provider, model=args.model,
    instruction='You are a tech lead.',
    http_options=http_options, thinking=args.thinking,
    leader_tools=[read_file],
    agent_tools=[write_file, read_file],
), scheduler)
scheduler.register(team)
team.start()

time.sleep(0.1)


def team_chat(message, timeout=None):
    msg = Message(sender=make_id(), recipient=team.id, type='text', payload=message)
    reply = scheduler.request(msg, timeout=timeout)
    return reply.payload


print('=' * 60)
print('Team demo: leader creates sub-agents dynamically')
print('=' * 60)
r = team_chat('write a python `heap sort` tutorial to output.md')
print(f'\n\nTeam result: {r if r else "empty"}')

team.stop()
scheduler.shutdown()