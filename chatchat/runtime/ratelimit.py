from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rpm: int, clock=time.monotonic, sleep=None):
        self.rate = max(rpm, 1) / 60.0
        self.capacity = float(max(rpm, 1))
        self.tokens = self.capacity
        self.updated = clock()
        self.clock = clock
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()

    async def acquire(self, check=None):
        async with self._lock:
            while True:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
                await self._sleep(min(0.5, wait))
                if check is not None:
                    check()


_BUCKETS: dict[str, TokenBucket] = {}


def configure(limits: dict, clock=time.monotonic, sleep=None) -> None:
    """Arm the process-wide provider buckets. Providers not mentioned keep
    whatever bucket they already have."""
    for name, rpm in dict(limits or {}).items():
        _BUCKETS[str(name).lower()] = TokenBucket(int(rpm), clock=clock, sleep=sleep)


def reset() -> None:
    _BUCKETS.clear()


async def acquire(provider: str, check=None) -> None:
    bucket = _BUCKETS.get(str(provider or "").lower())
    if bucket is not None:
        await bucket.acquire(check=check)
