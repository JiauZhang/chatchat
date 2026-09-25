import asyncio

from chatchat.client import ToolUse
from chatchat.team.agents import AgentRegistry
from chatchat.hooks.events import AGENT_PROGRESS, register_runtime_handler
from chatchat.tool import Tool
from helpers import mock_team

_USAGE = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
          'prompt_tokens_details': {'cached_tokens': 40}}


def _call_tool_once(tool_name, reply, **args):
    def respond(messages, tools=None, *, stream_cb=None):
        if not any(isinstance(m.get('content'), list) for m in messages):
            return [ToolUse(tool_name, args, 't1')]
        return reply

    return respond


def _counting_tool(name, calls):
    def run(context, **kw):
        calls[name] = calls.get(name, 0) + 1
        return f"{name}:{kw.get('x')}"

    return Tool(tool=run, name=name, description=name,
                parameters={'type': 'object', 'properties': {'x': {'type': 'int'}}})


def test_spawn_subagent_emits_progress_with_usage():
    events = []
    register_runtime_handler(lambda ev: events.append(ev))

    async def main():
        team = mock_team('prog', handler=_call_tool_once('ping', '子任务完成', x=1),
                         usage=_USAGE)
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
    calls = {}

    async def main():
        team = mock_team('t', handler=_call_tool_once('ping', 'done', x=1),
                         tools=[_counting_tool('ping', calls)])
        names = [t['name'] for t in team.tool_schemas(team.tool_context)]
        return names, await team.query('hi', timeout=10)

    names, ans = asyncio.run(main())
    assert 'ping' in names
    assert 'SendMessage' in names
    assert ans == 'done'
    assert calls == {'ping': 1}


def test_standalone_subagent_uses_its_own_definition_tools():
    calls = {}

    async def main():
        team = mock_team('sa', handler=_call_tool_once('my_tool',
                                                       'subagent 完成.', x=1))
        team.define_agent('coder', system_prompt='你是编码 agent',
                          tools=[_counting_tool('my_tool', calls)], default=False)
        return await team.spawn_subagent('帮我算', subagent_type='coder')

    assert asyncio.run(main()).endswith('subagent 完成.')
    assert calls == {'my_tool': 1}


def test_spawn_subagent_defaults_general_purpose():
    async def main():
        team = mock_team('gp', handler=lambda m, t=None, **kw: '默认答复')
        result = await team.spawn_subagent('hi')
        return result, len(team.agents)

    result, n = asyncio.run(main())
    assert result == '默认答复'
    assert n == 2


def test_agent_registry_remove_drops_the_type():
    registry = AgentRegistry()
    registry.define('coder', system_prompt='p')
    assert registry.remove('coder')
    assert not registry.remove('coder')
    assert registry.find('coder') is None
    assert 'coder' not in registry.types()


def test_removing_the_default_repoints_the_default():
    registry = AgentRegistry()
    registry.define('coder', system_prompt='p')
    registry.define('reviewer', system_prompt='p', default=True)
    registry.remove('reviewer')
    assert registry.get(None).agent_type == 'coder'


def test_team_remove_agent_definition():
    async def main():
        team = mock_team('rm', handler=lambda *a, **k: 'x')
        team.define_agent('coder', system_prompt='p')
        assert team.remove_agent_definition('coder')
        assert team.agent_defs.find('coder') is None
        assert not team.remove_agent_definition('coder')

    asyncio.run(main())
