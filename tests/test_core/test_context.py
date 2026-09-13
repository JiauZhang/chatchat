import asyncio

from chatchat.core.abort import AbortSignal
from chatchat.core.context import AgentContext, current_agent, is_in_process, \
    spawn_task, run_with_context


def _make_ctx(name):
    return AgentContext(agent_id=f'{name}@team', agent_name=name, team_name='team',
                        abort=AbortSignal(), leader=(name == 'team-lead'))


def test_run_with_context_sets_and_restores():
    outer = _make_ctx('a')
    inner = _make_ctx('b')
    assert current_agent() is None

    async def main():
        async def probe():
            return current_agent().agent_name
        res = await run_with_context(inner, probe())
        assert res == 'b'
        assert current_agent() is None

    asyncio.run(main())


def test_spawn_task_isolates_concurrent_contexts():
    async def main():
        seen = {}

        async def work(name):
            agent = _make_ctx(name)
            await asyncio.sleep(0.01 if name == 'x' else 0.02)
            seen[name] = current_agent().agent_name

        a = spawn_task(_make_ctx('x'), work('x'), name='x')
        b = spawn_task(_make_ctx('y'), work('y'), name='y')
        await asyncio.gather(a, b)
        assert seen == {'x': 'x', 'y': 'y'}

    asyncio.run(main())


def test_no_context_means_not_in_process():
    assert current_agent() is None
    assert not is_in_process()