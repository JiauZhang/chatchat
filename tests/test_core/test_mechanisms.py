import asyncio

from chatchat.client import MockClient
from chatchat.core.task import is_terminal_task_status
from chatchat.core.team import Team


LEAD = 'lead'


def last_text(agent):
    for m in reversed(agent.messages):
        if isinstance(m.get('content'), str):
            return m['content']
    return ''


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
        team = Team('ac', client_factory=factory, lead_instruction=LEAD,
                    context_window=40_001, compact_reserve=40_000)
        for i in range(14):
            team.lead.messages.append({'role': 'user', 'content': f'm{i}'})
        team.lead.messages[1]['usage'] = {'prompt_tokens': 5_000,
                                          'completion_tokens': 10}
        return await team.maybe_compact(list(team.lead.messages))

    result = asyncio.run(main())
    assert any('conversation summary' in str(m.get('content'))
               for m in result)
    assert result[0]['content'] == 'm0'
    assert 'm13' in str(result[-1]['content'])


def test_compaction_announces_what_it_folded_in():
    events = []

    async def respond(messages, tools=None, *, stream_cb=None):
        if len(messages) > 3:
            return 'the gist of it'
        return 'ok'

    def factory(instruction, model=None):
        return MockClient(handler=respond)

    async def main():
        from chatchat.hooks import events as hook_events

        team = Team('ac2', client_factory=factory, lead_instruction=LEAD,
                    context_window=40_001, compact_reserve=40_000)
        for i in range(14):
            team.lead.messages.append({'role': 'user', 'content': f'm{i}'})
        team.lead.messages[1]['usage'] = {'prompt_tokens': 5_000,
                                          'completion_tokens': 10}
        hook_events.register_runtime_handler(
            lambda ev: events.append(ev) if ev.kind == hook_events.AGENT_COMPACT
            else None)
        before = len(team.lead.messages)
        result = await team.maybe_compact(list(team.lead.messages))
        return before, result

    before, result = asyncio.run(main())
    assert events, 'compaction announced nothing'
    assert events[0].data['summarized'] == before - len(result) + 1
    assert events[0].data['summary'] == 'the gist of it'
