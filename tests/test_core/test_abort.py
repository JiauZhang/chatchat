import asyncio

import pytest

from chatchat.core.abort import Abort, AbortSignal


def test_abort_initial():
    s = AbortSignal()
    assert not s.aborted
    s.check()


def test_abort_raises():
    s = AbortSignal()
    s.abort()
    assert s.aborted
    with pytest.raises(Abort):
        s.check()


def test_abort_idempotent():
    s = AbortSignal()
    s.abort()
    s.abort()
    assert s.aborted


def test_abort_wait_wakes():
    async def main():
        s = AbortSignal()

        async def waiter():
            await s.wait()
            return True

        t = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        s.abort()
        assert await t is True

    asyncio.run(main())