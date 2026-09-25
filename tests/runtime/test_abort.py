import asyncio

import pytest

from chatchat.runtime.abort import Abort, AbortSignal


def test_a_fresh_signal_passes_and_aborting_twice_stays_aborted():
    s = AbortSignal()
    s.check()
    s.abort()
    s.abort()
    assert s.aborted
    with pytest.raises(Abort):
        s.check()


def test_wait_wakes_on_abort_and_returns_at_once_afterwards():
    async def main():
        s = AbortSignal()
        waiter = asyncio.create_task(s.wait())
        await asyncio.sleep(0)
        assert not waiter.done()
        s.abort()
        await waiter
        await s.wait()

    asyncio.run(main())