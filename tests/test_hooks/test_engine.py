import asyncio
import time

import pytest

from chatchat.client import MockClient, ToolUse
from chatchat.team import Team


@pytest.fixture
def team():
    def make(handler=None, hooks=True):
        return Team('demo', MockClient(handler=handler), hooks=hooks)

    return make


def test_function_hook_allow(team):
    async def main():
        t = team()
        seen = []
        t.hooks.on('PreToolUse', fn=lambda inp: seen.append(inp['tool_name']) or True)
        await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert seen == ['Bash']

    asyncio.run(main())


def test_function_hook_block(team):
    async def main():
        t = team()
        t.hooks.on('PreToolUse', fn=lambda inp: False)
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert agg.blocking_error is not None
        assert not agg.success

    asyncio.run(main())


def test_function_hook_json_updated_input(team):
    async def main():
        t = team()
        t.hooks.on('PreToolUse', fn=lambda inp: {
            'decision': 'allow', 'updatedInput': {'command': 'git x'}})
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {'command': 'git y'})
        assert agg.success
        assert agg.updated_input == {'command': 'git x'}

    asyncio.run(main())


def test_command_hook_exit_two_blocks(team):
    async def main():
        t = team()
        t.hooks.register('PreToolUse', 'Bash', command='echo nope; exit 2')
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert agg.blocking_error is not None
        assert 'nope' in agg.blocking_error.blocking_error

    asyncio.run(main())


def test_command_hook_echo_success(team):
    async def main():
        t = team()
        t.hooks.register('PreToolUse', 'Bash', command='echo hello')
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert agg.success
        assert any('hello' in r.stdout for r in agg.results)

    asyncio.run(main())


def test_matched_hooks_run_in_parallel(team):
    async def main():
        t = team()

        def slow(_):
            time.sleep(0.3)
            return True

        t.hooks.register('Stop', fn=slow)
        t.hooks.register('Stop', fn=slow)
        start = time.monotonic()
        await t.hooks.execute_stop_hooks(t.lead)
        assert time.monotonic() - start < 0.55

    asyncio.run(main())


def test_per_hook_timeout(team):
    async def main():
        t = team()

        async def slow(_):
            await asyncio.sleep(1)
            return True

        t.hooks.register('Stop', fn=slow, timeout=0.05)
        agg = await t.hooks.execute_stop_hooks(t.lead)
        assert any(r.outcome == 'non_blocking_error' and 'timed out' in r.message
                   for r in agg.results)

    asyncio.run(main())


def test_matcher_filters(team):
    async def main():
        t = team()
        t.hooks.register('PreToolUse', 'Bash', fn=lambda inp: True)
        t.hooks.register('PreToolUse', 'Read', fn=lambda inp: True)
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert len(agg.results) == 1

    asyncio.run(main())


def test_session_hook_remove(team):
    async def main():
        t = team()
        hid = t.hooks.register('Stop', fn=lambda inp: True)
        t.hooks.remove_hook(hid)
        agg = await t.hooks.execute_stop_hooks(t.lead)
        assert agg.results == []

    asyncio.run(main())


def test_once_runs_single_time(team):
    async def main():
        t = team()
        count = {'n': 0}

        def inc(_):
            count['n'] += 1
            return True

        t.hooks.register('Stop', fn=inc, once=True)
        await t.hooks.execute_stop_hooks(t.lead)
        await t.hooks.execute_stop_hooks(t.lead)
        assert count['n'] == 1

    asyncio.run(main())


def test_user_prompt_submit_block_reaches_turn(team):
    async def main():
        t = team()
        t.hooks.on('UserPromptSubmit', fn=lambda inp: False)
        answer = await t.query('go')
        assert 'blocked by hook' in answer

    asyncio.run(main())


def test_stop_hook_blocking_feedback_continues_turn(team):
    """对齐 claude：Stop hook 阻断时反馈回流为新 turn，turn 不结束。"""
    calls = []

    async def respond(messages, tools=None, *, stream_cb=None):
        texts = [c for c in (m.get('content') for m in messages)
                 if isinstance(c, str)]
        if any('Stop hook feedback' in c for c in texts):
            return 'after feedback'
        calls.append(1)
        return 'initial'

    async def main():
        t = team(handler=respond)
        # claude 协议：hook 通过 stop_hook_active 防止无限续聊
        t.hooks.on('Stop', fn=lambda inp: False if not inp.get('stop_hook_active')
                   else True)
        return await t.query('go'), len(calls)

    ans, initial_calls = asyncio.run(main())
    assert ans == 'after feedback'
    assert initial_calls == 1


def test_teammate_idle_hook_fires_when_teammate_turn_ends(team):
    seen = []

    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        return [ToolUse('create_agent', {'prompt': 'x', 'name': 'worker'}, 't1')]

    async def main():
        t = team(handler=respond)
        t.hooks.on('TeammateIdle', fn=lambda inp: seen.append(1) or True)
        await t.query('go')
        teammate = t.agents.get(t.agent_id('worker'))
        if teammate is not None:
            await teammate.wait_idle(3.0)
        return seen

    assert asyncio.run(main())


def test_pre_tool_block_reaches_agent_as_tool_result(team):
    async def respond(messages, tools):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'stop'
        return [ToolUse('send_message', {'to': 'nobody'}, 't1')]

    async def main():
        t = team(handler=respond)
        t.hooks.on('PreToolUse', fn=lambda inp: False)
        await t.query('go')
        contents = [m.get('content') for m in t.lead.messages
                    if isinstance(m.get('content'), list)]
        assert any('hook blocked tool' in (r.get('content') or '')
                   for rs in contents for r in rs)

    asyncio.run(main())


def test_internal_agent_skips_emits(team):
    async def main():
        t = team()
        seen = []
        t.hooks.on('UserPromptSubmit', fn=lambda inp: seen.append(1) or True)
        t.lead._internal = True
        await t.query('go')
        assert seen == []

    asyncio.run(main())


def test_no_hooks_short_circuit(team):
    async def main():
        t = team(hooks=False)
        seen = []
        t.hooks.on('UserPromptSubmit', fn=lambda inp: seen.append(1) or True)
        ans = await t.query('go')
        assert ans == 'ok'
        assert seen == []

    asyncio.run(main())
