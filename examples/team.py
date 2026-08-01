"""
多层级 Team 示例：任务依赖链 + 跨层级协作

展示真实软件开发场景中的任务依赖关系：
  需求分析 → UI设计 → 开发 → 测试

结构:
Team(研发部) ── 项目经理
├── Team(产品组) ── 产品经理 -> 产品助理, 需求分析师
├── Team(设计组) ── 设计主管 -> UI设计师, 交互设计师
├── Team(开发组) ── 技术主管 -> 前端开发, 后端开发, 数据库工程师
└── Team(测试组) ── 测试主管 -> 测试工程师, 自动化测试

功能覆盖:
  - 多层级 Team 创建与嵌套
  - 任务依赖链 (depends_on)
  - 跨层级任务分配（非阻塞，Task 实体传递）
  - 子团队内 call_meeting 讨论
  - 子团队内 assign_task 任务分解
  - Agent 间 send_message 协作
  - update_task 状态更新
  - list_tasks 汇总查询
"""
import os, sys, random, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agent import AgentConfig
from chatchat.team import Team, TeamConfig
from chatchat.tool import tool
from chatchat.event import EventBus, Event


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


def handle_team_start(event: Event):
    print(f'[team:start   {event.source:>10}] {event.data.get("message","")[:60]}')


def handle_team_step(event: Event):
    print(f'[team:step    {event.source:>10}] {event.data.get("content","")}')


def handle_team_end(event: Event):
    print(f'[team:end     {event.source:>10}] complete')


def handle_agent_start(event: Event):
    print(f'[agent:start  {event.source:>10}] {event.data.get("message","")[:60]}')


def handle_agent_step(event: Event):
    tcs = event.data.get('tool_calls', [])
    if tcs:
        names = [tc['name'] for tc in tcs]
        arys = [str(tc.get('arguments', ''))[:40] for tc in tcs]
        print(f'[agent:step   {event.source:>10}] {names} {arys}')


def handle_agent_end(event: Event):
    content = (event.data.get('content', '') or '')[:60]
    print(f'[agent:end    {event.source:>10}] {content}...')


def handle_agent_error(event: Event):
    print(f'[agent:error  {event.source:>10}] {event.data.get("error","")}')


def handle_client_start(event: Event):
    print(f'[client:start {event.source:>10}] LLM 请求开始')


def handle_client_step(event: Event):
    d = event.data
    if d.get('response'):
        choices = d['response'].get('choices', [])
        if choices:
            content = choices[0].get('message', {}).get('content', '') or ''
            if content:
                print(f'[client:step  {event.source:>10}] {content}')
    elif d.get('delta'):
        content = d['delta'].get('content', '') or ''
        if content:
            print(content, end='', flush=True)


def handle_client_end(event: Event):
    print(f'\n[client:end   {event.source:>10}] LLM 响应完成')


def handle_client_error(event: Event):
    print(f'[client:error {event.source:>10}] {event.data.get("error","")[:80]}')


with EventBus() as bus:
    bus.subscribe('team:start', handle_team_start)
    bus.subscribe('team:step', handle_team_step)
    bus.subscribe('team:end', handle_team_end)
    bus.subscribe('agent:start', handle_agent_start)
    bus.subscribe('agent:step', handle_agent_step)
    bus.subscribe('agent:end', handle_agent_end)
    bus.subscribe('agent:error', handle_agent_error)
    bus.subscribe('client:start', handle_client_start)
    bus.subscribe('client:step', handle_client_step)
    bus.subscribe('client:end', handle_client_end)
    bus.subscribe('client:error', handle_client_error)

    with Team(
        name='研发部', provider=args.provider, model=args.model,
        event_bus=bus,
        leader=AgentConfig(
            name='项目经理',
            http_options=http_options, stream=False,
            instruction='你是项目经理，负责统筹整个研发团队。\n'
                        '团队包含 4 个子团队：产品组、设计组、开发组、测试组。\n'
                        '子团队负责人：产品经理、设计主管、技术主管、测试主管。\n'
                        '成员已就绪，无需使用 spawn_agent 创建新成员。\n'
                        '使用 create_task 创建任务时用 depends_on 指定依赖关系。\n'
                        'assign_task 会自动检查依赖是否已完成，未完成则拒绝分配。\n'
                        'assign_task 是非阻塞的，分配后任务由子团队异步执行。\n'
                        '之后用 list_tasks 查看任务状态，或用 send_message 询问进度。',
        ),
        members=[
            # 产品组
            TeamConfig(
                name='产品组', leader=AgentConfig(
                    name='产品经理',
                    http_options=http_options, stream=False,
                    instruction='你是产品经理，负责产品需求工作。\n'
                                '使用 list_members 查看已有成员，无需 spawn_agent 创建。\n'
                                '使用 create_task 创建子任务，用 assign_task 分配给组员。\n'
                                '需要讨论时可用 call_meeting 召集组员开会。',
                ), members=[
                    AgentConfig(
                        name='产品助理',
                        http_options=http_options, stream=False,
                        instruction='你是产品助理，协助产品经理整理需求文档。',
                    ),
                    AgentConfig(
                        name='需求分析师',
                        http_options=http_options, stream=False,
                        instruction='你是需求分析师，负责分析用户需求，编写需求规格说明书。',
                    ),
                ],
            ),
            # 设计组
            TeamConfig(
                name='设计组', leader=AgentConfig(
                    name='设计主管',
                    http_options=http_options, stream=False,
                    instruction='你是设计主管，负责设计团队管理。\n'
                                '使用 list_members 查看已有成员，无需 spawn_agent 创建。\n'
                                '使用 create_task 创建子任务，用 assign_task 分配给组员。\n'
                                '需要讨论时可用 call_meeting 召集组员开会。',
                ), members=[
                    AgentConfig(
                        name='UI设计师',
                        http_options=http_options, stream=False,
                        instruction='你是UI设计师，负责用户界面设计。',
                    ),
                    AgentConfig(
                        name='交互设计师',
                        http_options=http_options, stream=False,
                        instruction='你是交互设计师，负责交互流程设计。',
                    ),
                ],
            ),
            # 开发组
            TeamConfig(
                name='开发组', leader=AgentConfig(
                    name='技术主管',
                    http_options=http_options, stream=False,
                    instruction='你是技术主管，负责开发团队管理。\n'
                                '使用 list_members 查看已有成员，无需 spawn_agent 创建。\n'
                                '使用 create_task 创建子任务，用 assign_task 分配给组员。\n'
                                '组员之间可用 send_message 互相沟通。\n'
                                '需要讨论时可用 call_meeting 召集组员开会。',
                ), members=[
                    AgentConfig(
                        name='前端开发',
                        http_options=http_options, stream=False,
                        instruction='你是前端开发工程师。\n'
                                    '可用 send_message 与后端开发沟通 API 接口格式。',
                    ),
                    AgentConfig(
                        name='后端开发',
                        http_options=http_options, stream=False,
                        instruction='你是后端开发工程师。\n'
                                    '可用 send_message 与前端开发沟通 API 接口格式。',
                    ),
                    AgentConfig(
                        name='数据库工程师',
                        http_options=http_options, stream=False,
                        instruction='你是数据库工程师，负责数据库设计与管理。',
                    ),
                ],
            ),
            # 测试组
            TeamConfig(
                name='测试组', leader=AgentConfig(
                    name='测试主管',
                    http_options=http_options, stream=False,
                    instruction='你是测试主管，负责测试团队管理。\n'
                                '使用 list_members 查看已有成员，无需 spawn_agent 创建。\n'
                                '使用 create_task 创建子任务，用 assign_task 分配给组员。\n'
                                '需要讨论时可用 call_meeting 召集组员开会。',
                ), members=[
                    AgentConfig(
                        name='测试工程师',
                        http_options=http_options, stream=False,
                        instruction='你是测试工程师，负责功能测试、回归测试。',
                    ),
                    AgentConfig(
                        name='自动化测试',
                        http_options=http_options, stream=False,
                        instruction='你是自动化测试工程师，负责编写和执行自动化测试用例。',
                    ),
                ],
            ),
        ],
    ) as team:
        # ========== 只提供目标和要求，不指定具体操作步骤 ==========

        print('=' * 60)
        print('1. 项目经理制定计划并推进执行')
        print('=' * 60)
        r = team.chat(
            '我们要做一个用户登录功能。\n'
            '需要经历：需求分析 → UI设计 → 开发 → 测试 四个阶段，'
            '每个阶段依赖前一个阶段完成。\n'
            '请创建任务并推进执行，完成后向我汇报。'
        )
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('2. 继续推进剩余任务，确保全部完成')
        print('=' * 60)
        r = team.chat('检查进度，继续推进未完成的任务，确保所有任务都完成了。')
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('3. 汇总所有任务状态')
        print('=' * 60)
        r = team.chat('列出所有任务的状态，汇总报告给我')
        print(f'  {r}')
        bus.flush()