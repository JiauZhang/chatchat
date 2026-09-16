import asyncio

from chatchat.client import MockClient
from chatchat.core.task import is_terminal_task_status
from chatchat.team import Team


LEAD = 'lead'


def test_two_level_abort_stops_only_current_turn():
    calls = {'n': 0}

    async def responder(messages, tools=None, *, stream_cb=None):
        calls['n'] += 1
        if calls['n'] == 1:
            await asyncio.sleep(10)
        return '快答复'

    def factory(instruction, model=None):
        return MockClient(handler=responder)

    async def main():
        team = Team('ab', client_factory=factory, lead_instruction=LEAD)
        lead = team.lead
        lead.submit('hi')
        await asyncio.sleep(0.2)
        lead.abort_work()
        await asyncio.sleep(0.2)
        assert lead.is_running
        lead.submit('bye')
        for _ in range(100):
            if last_text(lead) == '快答复':
                break
            await asyncio.sleep(0.05)
        assert last_text(lead) == '快答复'
        await lead.stop()

    asyncio.run(main())


def test_task_terminal_on_stop():
    def factory(instruction, model=None):
        return MockClient(handler=lambda m, t=None, **k: 'ok')

    async def main():
        team = Team('t', client_factory=factory, lead_instruction=LEAD)
        lead = team.lead
        assert lead.task is not None
        assert lead.task.status == 'running'
        await lead.stop()
        return lead.task.status

    status = asyncio.run(main())
    assert is_terminal_task_status(status)


def test_model_call_timeout_degrades_gracefully():
    async def hang(messages, tools=None, *, stream_cb=None):
        await asyncio.sleep(60)
        return 'x'

    def factory(instruction, model=None):
        return MockClient(handler=hang)

    async def main():
        team = Team('tmo', client_factory=factory, lead_instruction='lead')
        team.lead.model_timeout = 1.5
        t0 = asyncio.get_running_loop().time()
        ans = await team.lead.chat('hi')
        elapsed = asyncio.get_running_loop().time() - t0
        return ans, elapsed, list(team.lead.messages)

    ans, elapsed, messages = asyncio.run(main())
    assert ans == ''
    assert elapsed < 8
    assert not any(m.get('role') == 'assistant' and 'timed out' in str(m.get('content'))
                   for m in messages if isinstance(m, dict))


def test_default_auto_compaction_summarizes_middle():
    calls = []

    async def respond(messages, tools=None, *, stream_cb=None):
        calls.append(len(messages))
        if len(messages) > 3:
            return 'conversation summary text'
        return 'ok'

    def factory(instruction, model=None):
        return MockClient(handler=respond)

    async def main():
        team = Team('ac', client_factory=factory, lead_instruction='lead',
                    compact_tokens=1)
        for i in range(14):
            team.lead.messages.append({'role': 'user', 'content': f'm{i}'})
        return await team.maybe_compact(list(team.lead.messages))

    result = asyncio.run(main())
    assert any('conversation summary' in str(m.get('content'))
               for m in result)
    assert result[0]['content'] == 'm0'
    assert 'm13' in str(result[-1]['content'])


def test_pluggable_compact_strategy():
    compacted = []

    async def responder(messages, tools=None, *, stream_cb=None):
        return 'ok'

    def factory(instruction, model=None):
        return MockClient(handler=responder)

    def strategy(messages):
        compacted.append(len(messages))
        return [m for m in messages if m.get('role') == 'assistant']

    async def main():
        team = Team('c', client_factory=factory, lead_instruction=LEAD)
        team.set_compact_strategy(strategy, threshold=1)
        await team.query('hi', timeout=5)
        return len(compacted)

    assert asyncio.run(main()) >= 1


def last_text(agent):
    for m in reversed(agent.messages):
        if isinstance(m.get('content'), str):
            return m['content']
    return ''
