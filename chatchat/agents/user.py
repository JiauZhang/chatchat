from __future__ import annotations

import asyncio

from chatchat.core.ids import make_id


class User:
    """A human/script as a first-class mailbox entity.

    Not an agent: no loop, no tools. It has an id + mailbox so other entities can
    address it via send_message and the script can await its own inbox. Sending
    uses the same routing as an agent (source = this user's id)."""

    def __init__(self, runtime):
        self._runtime = runtime
        self.id = make_id()
        self.mailbox: asyncio.Queue = asyncio.Queue()
        runtime.register_entity(self.id, 'user', self.mailbox)

    async def send(self, to_id: str, message: str) -> str:
        from chatchat.agents.builtin_tools import _send_one
        return await _send_one(self, to_id, message)

    async def receive(self, timeout: float) -> str:
        ev = await asyncio.wait_for(self.mailbox.get(), timeout=timeout)
        return ev.data

    def unregister(self):
        self._runtime.unregister_entity(self.id)