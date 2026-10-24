import asyncio

import pytest

from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.model_caller import ModelCaller


class _SlowClient:
    """A client that never answers, so the call times out."""

    def __init__(self):
        self.calls = 0

    async def respond(self, messages, tools=None, *, stream_cb=None):
        self.calls += 1
        await asyncio.sleep(10)
        return "never"


class _AnsweringClient:
    def __init__(self, answer="ok"):
        self.answer = answer
        self.calls = 0

    async def respond(self, messages, tools=None, *, stream_cb=None):
        self.calls += 1
        return self.answer


class _Spoke:
    """A client that says something and then hangs."""

    def __init__(self):
        self.calls = 0

    async def respond(self, messages, tools=None, *, stream_cb=None):
        self.calls += 1
        if stream_cb:
            stream_cb("partial", "text")
        await asyncio.sleep(10)
        return "never"


def test_an_answer_comes_back_without_a_second_call():
    client = _AnsweringClient("hello")
    caller = ModelCaller(client, timeout=5, retries=2)

    async def main():
        return await caller.ask([], [], abort=AbortSignal())

    answer, _ms = asyncio.run(main())
    assert answer == "hello"
    assert client.calls == 1


def test_a_call_that_keeps_timing_out_is_tried_again():
    client = _SlowClient()
    caller = ModelCaller(client, timeout=0.05, retries=2)

    async def main():
        return await caller.ask([], [], abort=AbortSignal())

    answer, _ms = asyncio.run(main())
    assert answer is None
    assert client.calls == 3


def test_a_call_that_already_said_something_is_not_tried_again():
    """Said once is said once; asking again would say it twice."""
    client = _Spoke()
    caller = ModelCaller(client, timeout=0.05, retries=2)

    async def main():
        return await caller.ask([], [], abort=AbortSignal(), spoke=lambda: True)

    answer, _ms = asyncio.run(main())
    assert answer is None
    assert client.calls == 1


def test_an_aborted_call_stops_at_once():
    client = _SlowClient()
    abort = AbortSignal()
    caller = ModelCaller(client, timeout=5, retries=2)

    async def main():
        async def abort_soon():
            await asyncio.sleep(0.02)
            abort.abort()

        await asyncio.gather(caller.ask([], [], abort=abort), abort_soon())

    with pytest.raises(Exception):
        asyncio.run(main())
    assert client.calls == 1
