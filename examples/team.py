"""
Team 综合示例
展示 Supervisor、Pipeline、Parallel 三种编排模式，以及嵌套 Team 结构。
通过 --mode 参数选择运行模式：supervisor / pipeline / parallel / nested
"""
import os, sys, argparse, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from chatchat.agent import Agent
from chatchat.team import Team
from chatchat.tool import tool
from chatchat.event import EventBus, Event

parser = argparse.ArgumentParser()
parser.add_argument('--provider', type=str, default='agnes')
parser.add_argument('--model', type=str, default='agnes-2.5-flash')
parser.add_argument('--timeout', type=int, default=None)
parser.add_argument('--proxy', type=str, default=None)
parser.add_argument('--mode', type=str, default='supervisor',
                    choices=['supervisor', 'pipeline', 'parallel', 'nested'])
args = parser.parse_args()

http_options = {}
if args.timeout:
    http_options['timeout'] = args.timeout
if args.proxy:
    http_options['proxy'] = args.proxy


# ====== 工具定义 ======
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


@tool(name='generate_outline', description='生成文章大纲')
def generate_outline(topic: str):
    return f'大纲：\n1. {topic} 背景\n2. {topic} 核心内容\n3. {topic} 展望'


@tool(name='expand_section', description='扩写章节')
def expand_section(section: str):
    return f'扩写：{section}'


@tool(name='polish_article', description='润色文章')
def polish_article(content: str):
    return f'润色后：{content}'


@tool(name='design_frontend', description='设计前端页面')
def design_frontend(spec: str):
    return f'前端方案：{spec}'


@tool(name='write_backend', description='编写后端接口')
def write_backend(spec: str):
    return f'后端接口：{spec}'


@tool(name='run_tests', description='执行测试')
def run_tests(spec: str):
    return f'测试结果：{spec}'


# ====== 事件处理器 ======
def handle_team_start(event: Event):
    d = event.data
    print(f'[team:start   {event.source:>10}] mode={d.get("mode","")} name={d.get("name","")}')


def handle_team_step(event: Event):
    print(f'[team:step    {event.source:>10}] {event.data.get("content", "")}')


def handle_team_end(event: Event):
    d = event.data
    print(f'[team:end     {event.source:>10}] mode={d.get("mode","")}')


def handle_agent_start(event: Event):
    print(f'[agent:start  {event.source:>10}] {event.data.get("message", "")[:60]}')


def handle_agent_step(event: Event):
    tcs = event.data.get('tool_calls', [])
    names = [tc['name'] for tc in tcs]
    print(f'[agent:step   {event.source:>10}] round {event.data.get("step", "")} -> {names}')


def handle_agent_end(event: Event):
    print(f'[agent:end    {event.source:>10}] {event.data.get("content", "")[:60]}...')


def handle_tool_start(event: Event):
    name = event.data.get('name', '')
    args = event.data.get('arguments', {})
    print(f'[tool:start   {event.source:>10}] "{name}" {args}')


def handle_tool_end(event: Event):
    name = event.data.get('name', '')
    result = event.data.get('result', '')
    print(f'[tool:end     {event.source:>10}] "{name}" done: {str(result)[:60]}...')


def handle_agent_error(event: Event):
    print(f'[agent:error  {event.source:>10}] {event.data.get("error", "")}')


# ====== 各模式演示 ======
def run_supervisor(bus):
    ticket_agent = Agent(
        name='票务专员', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options,
        instruction='你是票务专员，负责查询火车票信息和票价。',
        tools=[query_ticket, query_price],
    )
    manager = Agent(
        name='项目经理', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options,
        instruction='你是项目经理，分析用户需求后将任务分配给团队成员。\n可用成员：\n- 票务专员：查询火车票信息、票价',
    )
    team = Team(name='客服团队', leader=manager, event_bus=bus, max_depth=3)
    team.add_member(ticket_agent)
    prompt = '查一下上海到北京的火车票和票价'
    print(f'user> {prompt}\n')
    result = team.chat(prompt)
    bus.flush()
    print(f'\nassistant> {result}')


def run_pipeline(bus):
    writer = Agent(
        name='写手', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[generate_outline],
        instruction='你负责根据主题生成文章大纲。',
    )
    expander = Agent(
        name='扩写者', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[expand_section],
        instruction='你负责扩写文章章节。',
    )
    polisher = Agent(
        name='润色师', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[polish_article],
        instruction='你负责润色整篇文章。',
    )
    team = Team(name='写作流水线', leader=writer, event_bus=bus)
    team.add_member(writer)
    team.add_member(expander)
    team.add_member(polisher)

    prompt = '人工智能的发展趋势'
    print(f'user> {prompt}\n')
    result = team.pipeline(prompt)
    bus.flush()
    print(f'\nresult> {result}')


def run_parallel(bus):
    ticket_agent = Agent(
        name='票务专员', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options,
        instruction='你是票务专员，负责查询火车票信息。',
        tools=[query_ticket],
    )
    price_agent = Agent(
        name='价格专员', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options,
        instruction='你是价格专员，负责查询票价。',
        tools=[query_price],
    )
    team = Team(name='查询团队', leader=ticket_agent, event_bus=bus)
    team.add_member(ticket_agent)
    team.add_member(price_agent)

    tasks = {
        '票务专员': '查询上海到北京的火车票',
        '价格专员': '查询上海到北京的票价',
    }
    print(f'tasks> {tasks}\n')
    result = team.parallel(tasks)
    bus.flush()
    print(f'\nresults> {result}')


def run_nested(bus):
    frontend_leader = Agent(
        name='前端组长', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[design_frontend],
        instruction='你是前端组长，负责前端页面设计。\n可用成员：\n- 前端开发：实现前端页面',
    )
    frontend_dev = Agent(
        name='前端开发', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[design_frontend],
        instruction='你是前端开发工程师，负责实现前端页面。',
    )
    frontend_team = Team(name='前端组', leader=frontend_leader, event_bus=bus)
    frontend_team.add_member(frontend_dev)

    backend_leader = Agent(
        name='后端组长', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[write_backend],
        instruction='你是后端组长，负责后端接口设计。\n可用成员：\n- 后端开发：实现后端接口',
    )
    backend_dev = Agent(
        name='后端开发', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[write_backend],
        instruction='你是后端开发工程师，负责实现后端接口。',
    )
    backend_team = Team(name='后端组', leader=backend_leader, event_bus=bus)
    backend_team.add_member(backend_dev)

    test_leader = Agent(
        name='测试组长', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[run_tests],
        instruction='你是测试组长，负责测试计划。\n可用成员：\n- 测试工程师：执行测试',
    )
    test_dev = Agent(
        name='测试工程师', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options, tools=[run_tests],
        instruction='你是测试工程师，负责执行测试用例。',
    )
    test_team = Team(name='测试组', leader=test_leader, event_bus=bus)
    test_team.add_member(test_dev)

    director = Agent(
        name='研发总监', event_bus=bus, provider=args.provider, model=args.model,
        http_options=http_options,
        instruction='你是研发总监，协调前端、后端、测试团队。\n可用子团队负责人：\n- 前端组长\n- 后端组长\n- 测试组长',
    )
    dev_team = Team(name='研发部', leader=director, event_bus=bus, max_depth=5)
    dev_team.add_member(frontend_team)
    dev_team.add_member(backend_team)
    dev_team.add_member(test_team)

    print(f'=== 组织结构 ===')
    print(f'研发部 members: {[m.name for m in dev_team.members]}')
    print(f'is_leaf={dev_team.is_leaf}, 前端组 is_leaf={frontend_team.is_leaf}\n')

    prompt = '开发用户登录功能，包括前端页面、后端接口和测试用例'
    print(f'user> {prompt}\n')
    result = dev_team.chat(prompt)
    bus.flush()
    print(f'\nresult> {result}')


# ====== 主入口 ======
modes = {
    'supervisor': run_supervisor,
    'pipeline': run_pipeline,
    'parallel': run_parallel,
    'nested': run_nested,
}

with EventBus() as bus:
    bus.subscribe('team:start', handle_team_start)
    bus.subscribe('team:step', handle_team_step)
    bus.subscribe('team:end', handle_team_end)
    bus.subscribe('agent:start', handle_agent_start)
    bus.subscribe('agent:step', handle_agent_step)
    bus.subscribe('agent:end', handle_agent_end)
    bus.subscribe('agent:error', handle_agent_error)
    bus.subscribe('tool:start', handle_tool_start)
    bus.subscribe('tool:end', handle_tool_end)

    modes[args.mode](bus)