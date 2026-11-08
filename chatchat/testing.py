from __future__ import annotations

import asyncio
from inspect import signature
from typing import Optional

from chatchat.client import Usage
from chatchat.runtime.thinking import Thinking


class MockClient:
    def __init__(self, handler=None, thinking: Thinking = Thinking(), name: str = "", usage=None, model: str = None):
        self._handler = handler
        self.thinking = thinking
        self.name = name
        text = str(model) if model is not None else ""
        head, sep, tail = text.partition("/")
        if sep:
            self.provider, self.model = head, tail
        else:
            self.provider, self.model = "", model
        self._usage = usage
        self._last_usage = Usage()
        self._last_response_items = []

    async def respond(self, messages: list[dict], tools: Optional[list[dict]] = None, *, stream_cb=None):
        self._last_usage = Usage()
        self._last_response_items = []
        if self._handler is not None:
            params = signature(self._handler).parameters
            out = (
                self._handler(messages, tools, stream_cb=stream_cb)
                if ("stream_cb" in params)
                else self._handler(messages, tools)
            )
            out = await out if asyncio.iscoroutine(out) else out
        else:
            out = "ok"
        self._last_usage = Usage.from_dict(self._usage)
        return out
