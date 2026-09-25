from __future__ import annotations

import asyncio


class Abort(Exception):
    pass

class AbortSignal:
    def __init__(self):
        self._aborted = False
        self._waiters: list[asyncio.Future] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    def abort(self) -> None:
        if self._aborted:
            return
        self._aborted = True
        for fut in self._waiters:
            if not fut.done():
                fut.set_result(None)

    def check(self) -> None:
        if self._aborted:
            raise Abort()

    async def wait(self) -> None:
        if self._aborted:
            return
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
        finally:
            if fut in self._waiters:
                self._waiters.remove(fut)
