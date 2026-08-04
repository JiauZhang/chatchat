"""
多层级 Team 示例：任务依赖链 + 跨层级协作

展示真实软件开发场景中的任务依赖关系：
  需求分析 -> UI设计 -> 开发 -> 测试

结构:
Team(研发部) -- 项目经理
  - Team(产品组) -- 产品经理 -> 产品助理, 需求分析师
  - Team(设计组) -- 设计主管 -> UI设计师, 交互设计师
  - Team(开发组) -- 技术主管 -> 前端开发, 后端开发, 数据库工程师
  - Team(测试组) -- 测试主管 -> 测试工程师, 自动化测试
"""
import os, sys, random, argparse, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.scheduler import Scheduler
from chatchat.worker import Worker, WorkerConfig
from chatchat.team import Team, TeamConfig
from chatchat.message import ID, Message
from chatchat.tool import tool
from chatchat.rate_limiter import set_rate_limits


parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
args = parser.parse_args()

http_options = {}
if args.timeout:
    http_options['timeout'] = args.timeout
if args.proxy:
    http_options['proxy'] = args.proxy


set_rate_limits([
    {'provider': 'agnes', 'rpm': 20},
])


@tool(name='query_ticket', description='查询火车票数量',
      parameters={'type': 'object', 'properties': {
          'from_city': {'type': 'string'}, 'to_city': {'type': 'string'},
      }, 'required': ['from_city', 'to_city']})
def query_ticket(from_city, to_city):
    return f'{from_city} 到 {to_city} 还有 {random.randint(1, 10)} 张票。'


@tool(name='query_price', description='查询票价',
      parameters={'type': 'object', 'properties': {
          'from_city': {'type': 'string'}, 'to_city': {'type': 'string'},
      }, 'required': ['from_city', 'to_city']})
def query_price(from_city, to_city):
    return f'{from_city} 到 {to_city} 票价 {random.randint(100, 200)} 元。'


class EventMonitor(Worker):
    def __init__(self, scheduler):
        super().__init__(WorkerConfig(name='_monitor'), scheduler)
        self.id = ID(uid='_monitor', kind='monitor', name='monitor')

    def handle_message(self, msg):
        if msg.type != 'event':
            return None
        source = msg.sender.name if msg.sender else ''
        data = msg.payload or {}
        topic = msg.subtype

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
            print(f'[client:start {source:>10}] LLM 请求开始')
        elif topic == 'client:step':
            d = data
            if d.get('response'):
                choices = d['response'].get('choices', [])
                if choices:
                    content = choices[0].get('message', {}).get('content', '') or ''
                    if content:
                        print(f'[client:step  {source:>10}] {content}')
            elif d.get('delta'):
                content = d['delta'].get('content', '') or ''
                if content:
                    print(content, end='', flush=True)
        elif topic == 'client:end':
            print(f'\n[client:end   {source:>10}] LLM 响应完成')
        elif topic == 'client:error':
            print(f'[client:error {source:>10}] {data.get("error","")[:80]}')
        elif topic == 'tool:start':
            print(f'[tool:start   {source:>10}] {data.get("name","")}')
        elif topic == 'tool:end':
            print(f'[tool:end     {source:>10}] {data.get("name","")}')
        elif topic == 'tool:error':
            print(f'[tool:error   {source:>10}] {data.get("name","")}: {data.get("error","")}')
        return None


def make_worker_config(name, **kwargs):
    return WorkerConfig(
        name=name, provider=args.provider, model=args.model,
        http_options=http_options, stream=False,
        **kwargs,
    )


scheduler = Scheduler()

monitor = EventMonitor(scheduler)
scheduler.register(monitor)
for topic in ['agent:start', 'agent:step', 'agent:end', 'agent:error',
              'client:start', 'client:step', 'client:end', 'client:error',
              'tool:start', 'tool:end', 'tool:error']:
    scheduler.subscribe(topic, monitor.id)
monitor.start()

time.sleep(0.1)

team = Team(TeamConfig(
    name='研发部',
    leader=make_worker_config(
        name='项目经理',
        instruction='你是项目经理，负责统筹整个研发团队。\n'
                    '团队包含 4 个子团队：产品组、设计组、开发组、测试组。\n'
                    '子团队负责人：产品经理、设计主管、技术主管、测试主管。\n'
                    '成员已就绪，无需使用 create_agent 创建新成员。\n'
                    '使用 assign_task 分配任务给子团队负责人。\n'
                    '分配后任务由子团队异步执行，不会阻塞你。\n'
                    '没有需要处理的事时无需任何操作，等待通知即可。\n'
                    '使用 list_members 查看所有成员。',
    ),
    members=[
        TeamConfig(
            name='产品组', leader=make_worker_config(
                name='产品经理',
                instruction='你是产品经理，负责产品需求工作。\n'
                            '使用 list_members 查看已有成员。\n'
                            '使用 assign_task 分配任务给组员。\n'
                            '没有需要处理的事时无需任何操作，等待通知即可。\n'
                            '使用 send_msg 与组员沟通。',
            ), members=[
                make_worker_config(name='产品助理',
                    instruction='你是产品助理，协助产品经理整理需求文档。'),
                make_worker_config(name='需求分析师',
                    instruction='你是需求分析师，负责分析用户需求，编写需求规格说明书。'),
            ],
        ),
        TeamConfig(
            name='设计组', leader=make_worker_config(
                name='设计主管',
                instruction='你是设计主管，负责设计团队管理。\n'
                            '使用 list_members 查看已有成员。\n'
                            '使用 assign_task 分配任务给组员。\n'
                            '没有需要处理的事时无需任何操作，等待通知即可。\n'
                            '使用 send_msg 与组员沟通。',
            ), members=[
                make_worker_config(name='UI设计师',
                    instruction='你是UI设计师，负责用户界面设计。'),
                make_worker_config(name='交互设计师',
                    instruction='你是交互设计师，负责交互流程设计。'),
            ],
        ),
        TeamConfig(
            name='开发组', leader=make_worker_config(
                name='技术主管',
                instruction='你是技术主管，负责开发团队管理。\n'
                            '使用 list_members 查看已有成员。\n'
                            '使用 assign_task 分配任务给组员。\n'
                            '没有需要处理的事时无需任何操作，等待通知即可。\n'
                            '使用 send_msg 与组员沟通。',
            ), members=[
                make_worker_config(name='前端开发',
                    instruction='你是前端开发工程师。'),
                make_worker_config(name='后端开发',
                    instruction='你是后端开发工程师。'),
                make_worker_config(name='数据库工程师',
                    instruction='你是数据库工程师，负责数据库设计与管理。'),
            ],
        ),
        TeamConfig(
            name='测试组', leader=make_worker_config(
                name='测试主管',
                instruction='你是测试主管，负责测试团队管理。\n'
                            '使用 list_members 查看已有成员。\n'
                            '使用 assign_task 分配任务给组员。\n'
                            '没有需要处理的事时无需任何操作，等待通知即可。\n'
                            '使用 send_msg 与组员沟通。',
            ), members=[
                make_worker_config(name='测试工程师',
                    instruction='你是测试工程师，负责功能测试、回归测试。'),
                make_worker_config(name='自动化测试',
                    instruction='你是自动化测试工程师，负责编写和执行自动化测试用例。'),
            ],
        ),
    ],
), scheduler)
scheduler.register(team)
team.start()

time.sleep(0.1)


def team_chat(message, timeout=120):
    msg = Message(sender=ID(), recipient=team.id, type='text', payload=message)
    reply = scheduler.request(msg, timeout=timeout)
    return reply.payload


print('=' * 60)
print('1. 项目经理制定计划并推进执行')
print('=' * 60)
r = team_chat(
    '我们要做一个用户登录功能。\n'
    '需要经历：需求分析 -> UI设计 -> 开发 -> 测试 四个阶段，\n'
    '每个阶段依赖前一个阶段完成。\n'
    '请创建任务并推进执行，完成后向我汇报。'
)
print(f'  {r}')
time.sleep(0.5)

print()
print('=' * 60)
print('2. 继续推进剩余任务，确保全部完成')
print('=' * 60)
r = team_chat('检查进度，继续推进未完成的任务，确保所有任务都完成了。')
print(f'  {r}')
time.sleep(0.5)

print()
print('=' * 60)
print('3. 汇总所有任务状态')
print('=' * 60)
r = team_chat('列出所有任务的状态，汇总报告给我')
print(f'  {r}')
time.sleep(0.5)

team.stop()
monitor.stop()
scheduler.shutdown()