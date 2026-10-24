"""Asking the model, and waiting for it without waiting forever.

A call to the model can hang, and a call that hangs has to be given up on
and tried again. The rules for that - how long to wait, how many times to
try, when to stop trying because something was already said - are one thing,
so they live here rather than inside the conversation that asks.
"""

import asyncio
import time

from chatchat.hooks.events import AGENT_WARN, emit


class ModelCaller:
    """Calls the model and gives up on it when it takes too long.

    A call that already produced text is not retried: the model said
    something, and saying it again would say it twice.
    """

    def __init__(self, client, *, timeout: float = 120.0, retries: int = 2, agent_name: str = ""):
        self.client = client
        self.timeout = timeout
        self.retries = retries
        self.agent_name = agent_name

    async def ask(self, messages, tools, *, abort, stream=None, spoke=None):
        """The model's answer, or None when it kept timing out.

        None means every attempt timed out and nothing was said; the caller
        decides what to tell the model about that. A call that already said
        something is not tried again: said twice, it would be said twice.
        """
        attempt = 0
        while True:
            abort.check()
            started = time.monotonic()
            respond = asyncio.create_task(self.client.respond(messages, tools, stream_cb=stream))
            waiter = asyncio.create_task(abort.wait())
            answer = None
            try:
                await asyncio.wait_for(
                    asyncio.wait({respond, waiter}, return_when=asyncio.FIRST_COMPLETED),
                    timeout=self.timeout,
                )
                if abort.aborted:
                    abort.check()
                answer = await respond
            except asyncio.TimeoutError:
                pass
            finally:
                if not waiter.done():
                    waiter.cancel()
                if not respond.done():
                    respond.cancel()
                    try:
                        await respond
                    except (asyncio.CancelledError, Exception):
                        pass
            if answer is not None:
                return answer, int((time.monotonic() - started) * 1000)
            attempt += 1
            if spoke is not None and spoke():
                return None, int((time.monotonic() - started) * 1000)
            if attempt > self.retries:
                return None, int((time.monotonic() - started) * 1000)
            emit(
                AGENT_WARN,
                agent=self.agent_name,
                text=(f"model call timed out after {self.timeout}s, retrying ({attempt}/{self.retries})"),
            )
