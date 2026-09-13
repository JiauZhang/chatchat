import asyncio

from chatchat.core.task import Task, generate_task_id, is_terminal_task_status, \
    wait_for_terminal


def test_terminal_status():
    for s in ('completed', 'failed', 'killed'):
        assert is_terminal_task_status(s)
    assert not is_terminal_task_status('running')
    assert not is_terminal_task_status('pending')


def test_generate_task_id_prefix():
    assert generate_task_id('in_process_teammate').startswith('t')
    assert generate_task_id('local_agent').startswith('a')
    assert len(generate_task_id('in_process_teammate')) == 9


def test_wait_for_terminal_join():
    async def main():
        t = Task(id='t1', type='in_process_teammate', agent_id='a@team')

        async def work():
            await asyncio.sleep(0.02)
            t.set_terminal('completed')

        asyncio.create_task(work())
        status = await wait_for_terminal(t)
        assert status == 'completed'
        assert t.terminal

    asyncio.run(main())


def test_wait_for_already_terminal_returns():
    async def main():
        t = Task(id='t1', type='in_process_teammate', agent_id='a@team')
        t.set_terminal('failed')
        assert await wait_for_terminal(t) == 'failed'

    asyncio.run(main())