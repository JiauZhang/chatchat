import asyncio

from chatchat.hooks.events import (AGENT_TEXT, emit,
                                   register_runtime_handler)
from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.context import AgentContext, spawn_task


def _ctx(name, team):
    return AgentContext(agent_id=name, agent_name=name, team_name=team,
                        abort=AbortSignal())


def test_emit_carries_the_team_of_the_agent_that_emitted():
    seen = []
    unregister = register_runtime_handler(seen.append)
    try:
        asyncio.run(_emit_from_two_teams())
    finally:
        unregister()
    assert [(ev.agent, ev.team) for ev in seen] == [('one', 'pyclaw-1'),
                                                    ('two', 'pyclaw-2')]


async def _emit_from_two_teams():
    first = spawn_task(_ctx('one', 'pyclaw-1'), _emit_once('one'))
    second = spawn_task(_ctx('two', 'pyclaw-2'), _emit_once('two'))
    await asyncio.gather(first, second)


async def _emit_once(name):
    emit(AGENT_TEXT, agent=name, delta=name)


def test_emit_takes_an_explicit_team_for_a_team_level_event():
    seen = []
    unregister = register_runtime_handler(seen.append)
    try:
        emit('team.settled', team='pyclaw-9')
    finally:
        unregister()
    assert seen[0].team == 'pyclaw-9'
