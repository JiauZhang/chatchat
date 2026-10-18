import asyncio

import chatchat.client as client_mod
import chatchat.runtime.ratelimit as ratelimit
from chatchat.client import Client
from chatchat.protocols import get_protocol


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.now += delay


def test_a_bucket_admits_the_first_burst_immediately():
    async def main():
        clock = FakeClock()
        bucket = ratelimit.TokenBucket(30, clock=clock, sleep=clock.sleep)
        for _ in range(30):
            await bucket.acquire()
        return clock.now - 1000.0

    assert asyncio.run(main()) == 0


def test_a_bucket_throttles_beyond_its_rpm():
    async def main():
        clock = FakeClock()
        bucket = ratelimit.TokenBucket(30, clock=clock, sleep=clock.sleep)
        for _ in range(30):
            await bucket.acquire()
        await bucket.acquire()
        return clock.now - 1000.0

    assert asyncio.run(main()) == 2.0


def test_a_bucket_refills_while_idle():
    async def main():
        clock = FakeClock()
        bucket = ratelimit.TokenBucket(30, clock=clock, sleep=clock.sleep)
        await bucket.acquire()
        clock.now += 60.0
        start = clock.now
        for _ in range(30):
            await bucket.acquire()
        return clock.now - start

    assert asyncio.run(main()) == 0


def test_configure_is_keyed_by_provider_and_reset_clears():
    ratelimit.reset()
    ratelimit.configure({"DeepSeek": 30})
    assert ratelimit._BUCKETS["deepseek"].rate == 0.5
    ratelimit.reset()
    assert ratelimit._BUCKETS == {}


def test_the_client_funnel_acquires_for_its_provider(monkeypatch):
    ratelimit.reset()
    seen = []

    async def fake_acquire(provider, check=None):
        seen.append(provider)

    monkeypatch.setattr(ratelimit, "acquire", fake_acquire)

    c = Client.__new__(Client)
    c.provider = "deepseek"
    c.model = "deepseek-flash"
    c.thinking = __import__("chatchat.runtime.thinking", fromlist=["Thinking"]).Thinking("off")
    c.instruction = None
    c._protocol = get_protocol("openai")
    c.base_url = "https://api.deepseek.com"
    c.api_key = "x"
    c._headers = {}
    c._timeout = client_mod.aiohttp.ClientTimeout(total=30)
    c._last_usage = client_mod.Usage()

    def fake_post(self, url, json=None, headers=None, timeout=None):
        class _Resp:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def raise_for_status(self):
                return None

            async def content_aiter(self):
                return
                yield

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            @property
            def content(self):
                return self

            async def json(self):
                return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        return _Resp()

    monkeypatch.setattr(client_mod.aiohttp.ClientSession, "post", fake_post)
    asyncio.run(c.respond([{"role": "user", "content": "hi"}]))
    assert seen == ["deepseek"]


def test_an_unconfigured_provider_never_waits():
    ratelimit.reset()

    async def main():
        await ratelimit.acquire("agnes")
        return "passed"

    assert asyncio.run(main()) == "passed"
