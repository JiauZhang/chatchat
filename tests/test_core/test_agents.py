import asyncio

from chatchat.client import MockClient, ToolUse
from chatchat.hooks.events import AGENT_PROGRESS, clear_runtime_sinks, \
    register_runtime_handler
from chatchat.team import Team
from chatchat.tool import Tool


def test_spawn_subagent_emits_progress_with_usage():
    events = []
    clear_runtime_sinks()
    register_runtime_handler(lambda ev: events.append(ev))

    async def respond(messages, tools=None, *, stream_cb=None):
        if not any(isinstance(m.get('content'), list) for m in messages):
            return [ToolUse('ping', {'x': 1}, 't1')]
        return '子任务完成'

    def factory(instruction, model=None):
        return MockClient(handler=respond,
                          usage={'prompt_tokens': 100, 'completion_tokens': 20,
                                 'total_tokens': 120,
                                 'prompt_tokens_details': {'cached_tokens': 40}})

    async def main():
        team = Team('prog', client_factory=factory)
        team.define_agent('coder', system_prompt='你是编码 agent')
        result = await team.spawn_subagent('干活', subagent_type='coder')
        return result, team

    result, team = asyncio.run(main())
    assert result == '子任务完成'
    progress = [ev for ev in events if ev.kind == AGENT_PROGRESS]
    assert progress[0].data['prompt'] == '干活'
    assert progress[0].data['subagent_type'] == 'coder'
    msgs = [ev.data['message'] for ev in progress if 'message' in ev.data]
    tool_use = next(m for m in msgs
                    if m['role'] == 'assistant'
                    and any(b.get('type') == 'tool_use' for b in m['content']))
    assert any(m['role'] == 'user' for m in msgs)
    assert progress[-1].data['done'] is True
    with_usage = [ev for ev in progress if 'usage' in ev.data]
    assert with_usage
    assert with_usage[0].data['usage']['prompt_tokens'] == 100
    assert with_usage[0].data['usage']['completion_tokens'] == 20


def test_team_members_run_injected_tools():
    called = {'ping': 0}

    def ping(context, **kw):
        called['ping'] += 1
        return f"pong:{kw.get('x')}"

    async def respond(messages, tools=None, *, stream_cb=None):
        if not any(isinstance(m.get('content'), list) for m in messages):
            return [ToolUse('ping', {'x': 1}, 't1')]
        return 'done'

    def factory(instruction, model=None):
        return MockClient(handler=respond)

    async def main():
        team = Team('t', client_factory=factory,
                    tools=[Tool(tool=ping, name='ping', description='ping',
                                parameters={'type': 'object',
                                            'properties': {'x': {'type': 'int'}}})])
        names = [t['name'] for t in team.tool_schemas(team.tool_context)]
        ans = await team.query('hi', timeout=10)
        return names, ans

    names, ans = asyncio.run(main())
    assert 'ping' in names
    assert 'send_message' in names
    assert called['ping'] == 1


def test_standalone_subagent_uses_its_own_definition_tools():
    called = {'my_tool': 0}

    def my_tool(context, **kw):
        called['my_tool'] += 1
        return f"tool 结果: {kw.get('x')}"

    async def sub_respond(messages, tools=None, *, stream_cb=None):
        if not any(isinstance(m.get('content'), list) for m in messages):
            return [ToolUse('my_tool', {'x': 1}, 't1')]
        return 'subagent 完成.'

    def factory(instruction, model=None):
        return MockClient(handler=sub_respond)

    async def main():
        team = Team('sa', client_factory=factory)
        team.define_agent('coder', system_prompt='你是编码 agent',
                          tools=[Tool(tool=my_tool, name='my_tool',
                                      description='a tool',
                                      parameters={'type': 'object',
                                                  'properties': {'x': {'type': 'int'}}})],
                          default=False)
        result = await team.spawn_subagent('帮我算', subagent_type='coder')
        return result

    assert asyncio.run(main()).endswith('subagent 完成.')
    assert called['my_tool'] == 1


def test_spawn_subagent_defaults_general_purpose():
    async def respond(messages, tools=None, *, stream_cb=None):
        return '默认答复'
    factory = lambda inst, model=None: MockClient(handler=respond)

    async def main():
        team = Team('gp', client_factory=factory)
        result = await team.spawn_subagent('hi')
        n = len(team.agents)
        return result, n

    result, n = asyncio.run(main())
    assert result == '默认答复'
    assert n == 2


def test_agent_registry_remove_drops_the_type():
    from chatchat.core.agents import AgentRegistry
    registry = AgentRegistry()
    registry.define('coder', system_prompt='p')
    assert registry.remove('coder')
    assert not registry.remove('coder')
    assert registry.find('coder') is None
    assert 'coder' not in registry.types()


def test_removing_the_default_repoints_the_default():
    from chatchat.core.agents import AgentRegistry
    registry = AgentRegistry()
    registry.define('coder', system_prompt='p')
    registry.define('reviewer', system_prompt='p', default=True)
    registry.remove('reviewer')
    assert registry.get(None).agent_type == 'coder'


def test_team_remove_agent_definition():
    factory = lambda inst, model=None: MockClient(handler=lambda *a, **k: 'x')

    async def main():
        team = Team('rm', client_factory=factory)
        team.define_agent('coder', system_prompt='p')
        assert team.remove_agent_definition('coder')
        assert team.agent_defs.find('coder') is None
        assert not team.remove_agent_definition('coder')

    asyncio.run(main())
