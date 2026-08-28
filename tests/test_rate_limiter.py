import asyncio
import pytest

from chatchat import rate_limiter
from chatchat.rate_limiter import (
    RateLimiterState,
    RateLimit,
    ProviderLimiter,
)


def _fast_forward(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(rate_limiter, '_now', lambda: t[0])

    async def fake_sleep(dt):
        t[0] += dt

    monkeypatch.setattr(rate_limiter, '_sleep', fake_sleep)
    return t


def _fast_time():
    return rate_limiter._now()


class TestRateLimiterState:
    async def test_rpm_limits_requests(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=5)
        for _ in range(5):
            await limiter.acquire()
            await limiter.release()
        t0 = _fast_time()
        await limiter.acquire()
        await limiter.release()
        elapsed = _fast_time() - t0
        assert elapsed >= 0.1

    async def test_rpm_no_limit_when_zero(self):
        limiter = RateLimiterState(rpm=0)
        t0 = _fast_time()
        for _ in range(100):
            await limiter.acquire()
            await limiter.release()
        elapsed = _fast_time() - t0
        assert elapsed < 0.5

    async def test_tpm_limits_tokens(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(tpm=100)
        for _ in range(3):
            await limiter.acquire()
            await limiter.release(actual_tokens=20)
        t0 = _fast_time()
        for _ in range(3):
            await limiter.acquire()
            await limiter.release(actual_tokens=20)
        elapsed = _fast_time() - t0
        assert elapsed >= 0.1

    async def test_tpm_no_limit_when_zero(self):
        limiter = RateLimiterState(tpm=0)
        t0 = _fast_time()
        for _ in range(100):
            await limiter.acquire()
            await limiter.release(actual_tokens=10000)
        elapsed = _fast_time() - t0
        assert elapsed < 0.5

    async def test_max_concurrent_limits_parallel(self):
        limiter = RateLimiterState(max_concurrent=3)
        running = 0
        peak = 0
        results = []
        lock = asyncio.Lock()

        async def worker(i):
            nonlocal running, peak
            await limiter.acquire()
            async with lock:
                running += 1
                peak = max(peak, running)
            await asyncio.sleep(0.05)
            async with lock:
                running -= 1
            results.append(i)
            await limiter.release()

        await asyncio.gather(*(worker(i) for i in range(6)))
        assert peak <= 3
        assert len(results) == 6

    async def test_max_concurrent_no_limit_when_zero(self):
        limiter = RateLimiterState(max_concurrent=0)

        async def worker():
            await limiter.acquire()
            await limiter.release()

        t0 = _fast_time()
        await asyncio.gather(*(worker() for _ in range(10)))
        elapsed = _fast_time() - t0
        assert elapsed < 0.5

    async def test_notify_429_slows_down_subsequent_requests(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=10)
        for _ in range(10):
            await limiter.acquire()
            await limiter.release()
        await limiter.notify_429()
        t0 = _fast_time()
        await limiter.acquire()
        await limiter.release()
        elapsed = _fast_time() - t0
        assert elapsed >= 0.1

    async def test_notify_429_no_rpm_means_noop(self):
        limiter = RateLimiterState(rpm=0)
        await limiter.notify_429()
        await limiter.acquire()
        await limiter.release()

    async def test_notify_429_sets_penalty_until(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=10)
        for _ in range(10):
            await limiter.acquire()
            await limiter.release()
        await limiter.notify_429()
        t0 = _fast_time()
        await limiter.acquire()
        await limiter.release()
        elapsed = _fast_time() - t0
        assert elapsed >= 0.5


class TestProviderLimiter:
    """Per-provider limiter owned by a client; context-manager admission +
    account() records real token usage for TPM."""
    async def test_context_manager_admits_within_rpm(self):
        limiter = ProviderLimiter(RateLimit(rpm=5, max_concurrency=2))
        async with limiter:
            pass  # no error, admitted

    async def test_account_records_real_usage(self, monkeypatch):
        _fast_forward(monkeypatch)
        state = RateLimiterState(tpm=10)
        limiter = ProviderLimiter.__new__(ProviderLimiter)
        limiter._state = state
        limiter.account(7)            # real usage, not estimated
        await asyncio.sleep(0)
        assert len(state._token_records) == 1
        assert state._token_records[0][1] == 7

    async def test_separate_providers_are_isolated(self):
        a = ProviderLimiter(RateLimit(max_concurrency=1))
        b = ProviderLimiter(RateLimit(max_concurrency=1))
        assert a.state is not b.state
        # each holds its own semaphore
        async with a:
            # b independent
            async with b:
                pass
