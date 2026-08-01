"""
多层级 Team 示例：4 个子团队 + 跨层级协作

结构:
Team(研发部) ── 项目经理
├── Team(产品组) ── 产品经理 -> 产品助理, 需求分析师
├── Team(设计组) ── 设计主管 -> UI设计师, 交互设计师
├── Team(开发组) ── 技术主管 -> 前端开发, 后端开发, 数据库工程师
└── Team(测试组) ── 测试主管 -> 测试工程师, 自动化测试
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
                        '成员已就绪，无需使用 spawn_agent 创建新成员。\n'
                        '使用 create_task 创建任务，用 assign_task 分配给各子团队负责人。\n'
                        '子团队负责人：产品经理、设计主管、技术主管、测试主管。',
        ),
        members=[
            # 产品组
            TeamConfig(
                name='产品组', leader=AgentConfig(
                    name='产品经理',
                    http_options=http_options, stream=False,
                    instruction='你是产品经理，负责产品需求工作。\n'
                                '可用成员：产品助理、需求分析师。\n'
                                '用 create_task 创建任务，用 assign_task 分配给组员。',
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
                                '可用成员：UI设计师、交互设计师。\n'
                                '用 create_task 创建任务，用 assign_task 分配给组员。',
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
                                '可用成员：前端开发、后端开发、数据库工程师。\n'
                                '用 create_task 创建任务，用 assign_task 分配给组员。\n'
                                '组员之间可用 send_message 互相沟通。',
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
                                '可用成员：测试工程师、自动化测试。\n'
                                '用 create_task 创建任务，用 assign_task 分配给组员。',
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
        print('=' * 60)
        print('1. 项目经理创建 4 个任务，分配给各子团队负责人')
        print('=' * 60)
        r = team.chat(
            '请创建以下 4 个任务并分配给对应的子团队负责人：\n'
            '1. 产品组 - 完成用户登录功能的需求分析（分配给产品经理）\n'
            '2. 设计组 - 完成登录页面的 UI 设计（分配给设计主管）\n'
            '3. 开发组 - 完成登录功能的开发（分配给技术主管）\n'
            '4. 测试组 - 完成登录功能的测试（分配给测试主管）'
        )
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('2. 各子团队负责人将任务分解给组员')
        print('=' * 60)
        r = team.chat(
            '请各子团队负责人将任务分解给组员：\n'
            '产品经理将需求分析任务分配给需求分析师；\n'
            '设计主管将 UI 设计任务分配给 UI设计师；\n'
            '技术主管将开发任务分配给前端开发和后端开发；\n'
            '测试主管将测试任务分配给测试工程师。'
        )
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('3. 跨组协作：前端开发 与 后端开发 确认 API 接口格式')
        print('=' * 60)
        r = team.chat(
            '让前端开发与后端开发通过 send_message 沟通确认登录 API 的接口格式，'
            '包括请求方法、参数和返回格式。'
        )
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('4. 组员完成任务后更新状态')
        print('=' * 60)
        r = team.chat(
            '让完成任务的组员使用 update_task 更新任务状态为 completed。\n'
            '需求分析已完成，UI 设计已完成，开发已完成，测试已完成。'
        )
        print(f'  {r}')
        bus.flush()

        print()
        print('=' * 60)
        print('5. 项目经理查看所有任务的整体状态')
        print('=' * 60)
        r = team.chat('列出所有任务的状态，汇总报告给我')
        print(f'  {r}')
        bus.flush()