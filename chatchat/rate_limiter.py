from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

_sleep = asyncio.sleep
_now = time.time


@dataclass
class RateLimit:
    """Per-provider rate limit config. 0 means unlimited."""
    rpm: int = 0
    tpm: int = 0
    max_concurrency: int = 0


class RateLimiterState:
    """Sliding-window (per-minute) limiter for requests and tokens, plus a
    concurrency Semaphore. Owned per-provider by a ProviderLimiter; not a
    global registry anymore."""

    def __init__(self, rpm: int = 0, tpm: int = 0, max_concurrent: int = 0):
        self.rpm = rpm
        self.tpm = tpm
        self._semaphore = asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        self._lock = asyncio.Lock()
        self._request_timestamps: deque[float] = deque()
        self._token_records: deque[tuple[float, int]] = deque()
        self._penalty_until: float = 0.0

    async def acquire(self, estimated_tokens: int = 0):
        if self._semaphore:
            await self._semaphore.acquire()
        await self._wait_for_penalty()
        await self._wait_for_rpm()
        await self._wait_for_tpm()

    async def _wait_for_penalty(self):
        while True:
            async with self._lock:
                remaining = self._penalty_until - _now()
            if remaining <= 0:
                return
            await _sleep(min(remaining, 1.0))

    async def notify_429(self):
        if self.rpm <= 0:
            return
        async with self._lock:
            now = _now()
            penalty_window = max(10.0, 60.0 / self.rpm * 2)
            self._penalty_until = now + penalty_window
            penalty_count = max(1, self.rpm // 2)
            for _ in range(penalty_count):
                self._request_timestamps.append(now)

    async def _wait_for_rpm(self):
        if self.rpm <= 0:
            return
        while True:
            async with self._lock:
                now = _now()
                while self._request_timestamps and now - self._request_timestamps[0] >= 60:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < self.rpm:
                    self._request_timestamps.append(now)
                    return
                sleep_time = 60 - (now - self._request_timestamps[0])
            if sleep_time > 0:
                await _sleep(sleep_time)

    async def _wait_for_tpm(self):
        if self.tpm <= 0:
            return
        while True:
            async with self._lock:
                now = _now()
                while self._token_records and now - self._token_records[0][0] >= 60:
                    self._token_records.popleft()
                total = sum(t for _, t in self._token_records)
                if total < self.tpm:
                    return
                oldest = self._token_records[0]
                sleep_time = 60 - (now - oldest[0])
            if sleep_time > 0:
                await _sleep(sleep_time)

    async def release(self, actual_tokens: int = 0):
        if actual_tokens > 0:
            async with self._lock:
                self._token_records.append((_now(), actual_tokens))
        if self._semaphore:
            self._semaphore.release()


class ProviderLimiter:
    """Per-provider limiter wrapper. Owned by a provider client; used as a
    context manager around the request. TPM is accounted from the real
    response usage via `account(used_tokens)`."""

    def __init__(self, cfg: RateLimit | None = None):
        cfg = cfg or RateLimit()
        self._state = RateLimiterState(cfg.rpm, cfg.tpm, cfg.max_concurrency)

    @property
    def state(self) -> RateLimiterState:
        return self._state

    async def __aenter__(self) -> "ProviderLimiter":
        await self._state.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        # Semaphore release happens in account()/release() after usage is known.
        pass

    async def acquire(self):
        await self._state.acquire()

    async def release(self, actual_tokens: int = 0):
        await self._state.release(actual_tokens)

    def account(self, used_tokens: int):
        """Record real token usage for TPM after the response returns."""
        if used_tokens > 0:
            asyncio.create_task(self._state.release(used_tokens))
