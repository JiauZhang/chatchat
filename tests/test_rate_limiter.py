import time
import threading
import pytest

from chatchat.rate_limiter import (
    RateLimiterState,
    set_rate_limits,
    get_rate_limiter,
)


def _fast_forward(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(time, 'time', lambda: t[0])
    monkeypatch.setattr(time, 'sleep', lambda s: t.__setitem__(0, t[0] + s))
    return t


class TestRateLimiterState:
    def test_rpm_limits_requests(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=5)
        for _ in range(5):
            limiter.acquire()
            limiter.release()
        t0 = time.time()
        limiter.acquire()
        limiter.release()
        elapsed = time.time() - t0
        assert elapsed >= 0.1

    def test_rpm_no_limit_when_zero(self):
        limiter = RateLimiterState(rpm=0)
        t0 = time.time()
        for _ in range(100):
            limiter.acquire()
            limiter.release()
        elapsed = time.time() - t0
        assert elapsed < 0.5

    def test_tpm_limits_tokens(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(tpm=100)
        for _ in range(3):
            limiter.acquire()
            limiter.release(actual_tokens=20)
        t0 = time.time()
        for _ in range(3):
            limiter.acquire()
            limiter.release(actual_tokens=20)
        elapsed = time.time() - t0
        assert elapsed >= 0.1

    def test_tpm_no_limit_when_zero(self):
        limiter = RateLimiterState(tpm=0)
        t0 = time.time()
        for _ in range(100):
            limiter.acquire()
            limiter.release(actual_tokens=10000)
        elapsed = time.time() - t0
        assert elapsed < 0.5

    def test_max_concurrent_limits_parallel(self):
        limiter = RateLimiterState(max_concurrent=3)
        acquired = [False] * 6
        results = []

        def worker(i):
            limiter.acquire()
            acquired[i] = True
            time.sleep(0.2)
            results.append(i)
            limiter.release()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        time.sleep(0.05)
        concurrent = sum(acquired)
        assert concurrent <= 3
        for t in threads:
            t.join()

    def test_max_concurrent_no_limit_when_zero(self):
        limiter = RateLimiterState(max_concurrent=0)
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            limiter.acquire()
            limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - t0
        assert elapsed < 0.5

    def test_notify_429_slows_down_subsequent_requests(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=10)
        for _ in range(10):
            limiter.acquire()
            limiter.release()
        limiter.notify_429()
        t0 = time.time()
        limiter.acquire()
        limiter.release()
        elapsed = time.time() - t0
        assert elapsed >= 0.1

    def test_notify_429_no_rpm_means_noop(self):
        limiter = RateLimiterState(rpm=0)
        limiter.notify_429()
        limiter.acquire()
        limiter.release()

    def test_notify_429_sets_penalty_until(self, monkeypatch):
        _fast_forward(monkeypatch)
        limiter = RateLimiterState(rpm=10)
        for _ in range(10):
            limiter.acquire()
            limiter.release()
        limiter.notify_429()
        t0 = time.time()
        limiter.acquire()
        limiter.release()
        elapsed = time.time() - t0
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

    def test_unconfigured_provider_returns_null(self):
        set_rate_limits([])
        limiter = get_rate_limiter('nonexistent')
        limiter.acquire()
        limiter.release()
        limiter.acquire(estimated_tokens=100)
        limiter.release(actual_tokens=50)

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