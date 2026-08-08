import os, sys, argparse, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler, on_event, off_event
from chatchat.agent import Agent, AgentConfig
from chatchat.team import Team, TeamConfig
from chatchat.message import ID, Message
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


def handle_event(topic, data):
    source = data.get('_source', '')
    if topic == 'agent:start':
        print(f'[agent:start  {source:>10}] {data.get("message","")[:60]}')
    elif topic == 'agent:step':
        tcs = data.get('tool_calls', [])
        if tcs:
            names = [tc['name'] for tc in tcs]
            arys = [str(tc.get('arguments', ''))[:40] for tc in tcs]
            print(f'[agent:step   {source:>10}] {names} {arys}')
    elif topic == 'agent:end':
        content = (data.get('content', '') or '')[:60]
        print(f'[agent:end    {source:>10}] {content}...')
    elif topic == 'agent:error':
        print(f'[agent:error  {source:>10}] {data.get("error","")}')
    elif topic == 'client:start':
        print(f'[client:start {source:>10}] LLM request started')
    elif topic == 'client:step':
        d = data
        if d.get('delta'):
            content = d['delta'].get('content', '') or ''
            if content.strip():
                print(content, end='', flush=True)
    elif topic == 'client:end':
        print(f'\n[client:end   {source:>10}] LLM response complete')
    elif topic == 'tool:start':
        print(f'[tool:start   {source:>10}] {data.get("name","")}')
    elif topic == 'tool:end':
        print(f'[tool:end     {source:>10}] {data.get("name","")}')
    elif topic == 'tool:error':
        print(f'[tool:error   {source:>10}] {data.get("name","")}: {data.get("error","")}')


def make_agent_config(name, **kwargs):
    return AgentConfig(
        name=name, provider=args.provider, model=args.model,
        http_options=http_options, stream=True, thinking=args.thinking,
        **kwargs,
    )


scheduler = Scheduler()

for topic in ['agent:start', 'agent:step', 'agent:end', 'agent:error',
              'client:start', 'client:step', 'client:end',
              'tool:start', 'tool:end', 'tool:error']:
    on_event(topic, handle_event)

time.sleep(0.1)

team = Team(TeamConfig(
    name='dev-team',
    leader=make_agent_config(
        name='lead',
        instruction='You are a tech lead. Use create_agent to create sub-agents for tasks. Use send_message to communicate with them.',
    ),
), scheduler)
scheduler.register(team)
team.start()

time.sleep(0.1)


def team_chat(message, timeout=None):
    msg = Message(sender=ID(), recipient=team.id, type='text', payload=message)
    reply = scheduler.request(msg, timeout=timeout)
    return reply.payload


print('=' * 60)
print('Team demo: leader creates sub-agents dynamically')
print('=' * 60)
r = team_chat('build a ticket booking system.')
print(f'  result: {r[:200] if r else "empty"}...')

team.stop()
scheduler.shutdown()