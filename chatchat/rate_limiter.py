import time
import threading
from collections import deque
from typing import Union


class _NullRateLimiter:
    rpm = 0
    tpm = 0

    def acquire(self, estimated_tokens: int = 0):
        pass

    def release(self, actual_tokens: int = 0):
        pass

    def notify_429(self):
        pass


class RateLimiterState:
    def __init__(self, rpm: int = 0, tpm: int = 0, max_concurrent: int = 0):
        self.rpm = rpm
        self.tpm = tpm
        self._semaphore = threading.Semaphore(max_concurrent) if max_concurrent > 0 else None
        self._lock = threading.Lock()
        self._request_timestamps: deque[float] = deque()
        self._token_records: deque[tuple[float, int]] = deque()
        self._penalty_until: float = 0.0

    def acquire(self, estimated_tokens: int = 0):
        if self._semaphore:
            self._semaphore.acquire()
        self._wait_for_penalty()
        self._wait_for_rpm()
        self._wait_for_tpm()

    def _wait_for_penalty(self):
        while True:
            with self._lock:
                remaining = self._penalty_until - time.time()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 1.0))

    def notify_429(self):
        if self.rpm <= 0:
            return
        with self._lock:
            now = time.time()
            penalty_window = max(10.0, 60.0 / self.rpm * 2)
            self._penalty_until = now + penalty_window
            penalty_count = max(1, self.rpm // 2)
            for _ in range(penalty_count):
                self._request_timestamps.append(now)

    def _wait_for_rpm(self):
        if self.rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.time()
                while self._request_timestamps and now - self._request_timestamps[0] >= 60:
                    self._request_timestamps.popleft()
                if len(self._request_timestamps) < self.rpm:
                    self._request_timestamps.append(time.time())
                    return
                sleep_time = 60 - (now - self._request_timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _wait_for_tpm(self):
        if self.tpm <= 0:
            return
        while True:
            with self._lock:
                now = time.time()
                while self._token_records and now - self._token_records[0][0] >= 60:
                    self._token_records.popleft()
                total = sum(t for _, t in self._token_records)
                if total < self.tpm:
                    return
                oldest = self._token_records[0]
                sleep_time = 60 - (now - oldest[0])
            if sleep_time > 0:
                time.sleep(sleep_time)

    def release(self, actual_tokens: int = 0):
        if actual_tokens > 0:
            with self._lock:
                self._token_records.append((time.time(), actual_tokens))
        if self._semaphore:
            self._semaphore.release()


_store: dict[str, RateLimiterState] = {}
_null = _NullRateLimiter()


def set_rate_limits(limits: list[dict]):
    global _store
    _store = {}
    for item in limits:
        provider = item.pop('provider')
        _store[provider] = RateLimiterState(**item)


def get_rate_limiter(provider: str) -> Union[_NullRateLimiter, RateLimiterState]:
    return _store.get(provider, _null)