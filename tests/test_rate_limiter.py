import asyncio
import pytest

from chatchat import rate_limiter
from chatchat.rate_limiter import (
    RateLimiterState,
    set_rate_limits,
    get_rate_limiter,
)


def _fast_forward(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(rate_limiter, '_now', lambda: t[0])

    async def fake_sleep(dt):
        t[0] += dt

    monkeypatch.setattr(rate_limiter, '_sleep', fake_sleep)
    return t


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


class TestSetRateLimits:
    def test_set_rate_limits_stores_by_provider(self):
        set_rate_limits([
            {'provider': 'agnes', 'rpm': 50, 'tpm': 200000},
            {'provider': 'openai', 'rpm': 10000},
        ])
        limiter = get_rate_limiter('agnes')
        assert limiter.rpm == 50
        assert limiter.tpm == 200000

        limiter2 = get_rate_limiter('openai')
        assert limiter2.rpm == 10000
        assert limiter2.tpm == 0

    async def test_unconfigured_provider_returns_null(self):
        set_rate_limits([])
        limiter = get_rate_limiter('nonexistent')
        await limiter.acquire()
        await limiter.release()
        await limiter.acquire(estimated_tokens=100)
        await limiter.release(actual_tokens=50)

    def test_reconfigure_overwrites(self):
        set_rate_limits([{'provider': 'x', 'rpm': 10}])
        set_rate_limits([{'provider': 'x', 'rpm': 20}])
        limiter = get_rate_limiter('x')
        assert limiter.rpm == 20

    def test_set_rate_limits_clear_others(self):
        set_rate_limits([
            {'provider': 'a', 'rpm': 10},
            {'provider': 'b', 'rpm': 20},
        ])
        set_rate_limits([{'provider': 'c', 'rpm': 30}])
        assert get_rate_limiter('a').rpm == 0
        assert get_rate_limiter('c').rpm == 30


def _fast_time():
    return rate_limiter._now()