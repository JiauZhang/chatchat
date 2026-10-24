import asyncio

from chatchat.runtime.pending import PendingWork


def test_work_that_was_given_is_work_that_is_outstanding():
    work = PendingWork()
    work.given()
    assert work.outstanding() == 1
    work.finished()
    assert work.outstanding() == 0
    assert work.settled()


def test_a_waiter_is_woken_when_the_work_is_finished():
    work = PendingWork()
    work.given()

    async def main():
        waiting = asyncio.create_task(work.wait(1.0))
        await asyncio.sleep(0.01)
        work.finished()
        work.idle()
        await waiting

    asyncio.run(main())


def test_a_moment_that_came_before_the_work_arrived_does_not_wake_a_waiter():
    """The agent was free a moment ago; that moment is not the work being
    asked about."""

    work = PendingWork()
    work.given()

    async def main():
        work.idle()
        try:
            await asyncio.wait_for(work.wait(0.05), 0.05)
            return "early"
        except asyncio.TimeoutError:
            return "waited"

    assert asyncio.run(main()) == "waited"


def test_a_waiter_asks_about_the_work_given_when_it_started_waiting():
    """Work handed over after the wait began is not waited for."""

    work = PendingWork()
    work.given()

    async def main():
        waiting = asyncio.create_task(work.wait(0.05))
        await asyncio.sleep(0.01)
        work.given()
        work.finished()
        work.idle()
        await asyncio.wait_for(waiting, 0.5)

    asyncio.run(main())


def test_nothing_outstanding_means_nothing_to_wait_for():
    work = PendingWork()

    async def main():
        await asyncio.wait_for(work.wait(0.5), 0.5)

    asyncio.run(main())
