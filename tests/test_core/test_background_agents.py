"""A sub-agent sent to the background must not hold its parent's turn open."""
import asyncio

from helpers import mock_team

from chatchat.core.team import LEAD_NAME as LEAD


async def _respond(messages, tools=None, *, stream_cb=None):
    return 'the answer'


def _team(name):
    return mock_team(name, handler=_respond)


async def _settle(rounds=20):
    for _ in range(rounds):
        await asyncio.sleep(0)


def test_a_background_sub_agent_returns_before_it_has_finished():
    async def main():
        team = _team('bg1')
        out = await team.execute_tool(
            'create_agent',
            {'prompt': 'look into it', 'run_in_background': True}, team.lead)
        started = team.background
        return out.text, list(started), team.lead.inbox.unread()

    text, running, unread = asyncio.run(main())
    assert 'running in the background' in text
    assert len(running) == 1
    assert unread == []


def test_the_answer_lands_in_the_parent_inbox_when_it_finishes():
    async def main():
        team = _team('bg2')
        await team.execute_tool(
            'create_agent',
            {'prompt': 'look into it', 'run_in_background': True}, team.lead)
        await _settle()
        return [m.text for m in team.lead.inbox.unread()], team.background

    notes, running = asyncio.run(main())
    assert len(notes) == 1
    assert 'the answer' in notes[0]
    assert running == {}


def test_a_background_sub_agent_is_stoppable_by_its_parent():
    async def main():
        team = _team('bg3')
        await team.execute_tool(
            'create_agent',
            {'prompt': 'look into it', 'run_in_background': True}, team.lead)
        agent_id = next(iter(team.background))
        stopped = await team.execute_tool('task_stop', {'agent_id': agent_id},
                                          team.lead)
        await _settle()
        return stopped.text, team.background, [m.text
                                              for m in team.lead.inbox.unread()]

    text, running, notes = asyncio.run(main())
    assert 'stopped' in text
    assert running == {}
    assert not any('the answer' in note for note in notes)


def test_a_named_teammate_is_not_also_a_background_sub_agent():
    async def main():
        team = _team('bg4')
        team.multi_agent = True
        return await team.execute_tool(
            'create_agent', {'prompt': 'look', 'name': 'worker',
                             'run_in_background': True}, team.lead)

    outcome = asyncio.run(main())
    assert outcome.text.startswith('Error:')


def test_an_internal_agent_cannot_send_its_work_to_the_background():
    async def main():
        team = _team('bg5')
        child = await team.spawn_child(LEAD, 'help with the thing',
                                       internal=True)
        return await team.execute_tool(
            'create_agent',
            {'prompt': 'look', 'run_in_background': True}, child)

    outcome = asyncio.run(main())
    assert outcome.text.startswith('Error:')


def test_the_report_carries_the_numbers_of_the_work_done():
    async def main():
        team = _team('bg8')
        await team.execute_tool('create_agent',
                                {'prompt': 'look into it',
                                 'run_in_background': True}, team.lead)
        agent_id = next(iter(team.background))
        await _settle()
        return team.agents[agent_id], [m.text
                                       for m in team.lead.inbox.unread()]

    agent, notes = asyncio.run(main())
    assert len(notes) == 1
    assert 'status: completed' in notes[0]
    assert f'tokens: {agent.total_usage.total_tokens}' in notes[0]
    assert 'the answer' in notes[0]


def test_a_sub_agent_that_fails_reports_that_instead_of_an_answer():
    async def blow_up(messages, tools=None, *, stream_cb=None):
        raise RuntimeError('the provider went away')

    async def main():
        team = mock_team('bg9', handler=blow_up)
        await team.execute_tool('create_agent',
                                {'prompt': 'look into it',
                                 'run_in_background': True}, team.lead)
        await _settle()
        return [m.text for m in team.lead.inbox.unread()]

    notes = asyncio.run(main())
    assert len(notes) == 1
    assert 'status: failed' in notes[0]
    assert 'the provider went away' in notes[0]
