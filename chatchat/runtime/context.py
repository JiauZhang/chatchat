from __future__ import annotations

import asyncio
import contextvars
from dataclasses import dataclass

from chatchat.runtime.abort import AbortSignal


@dataclass
class AgentContext:
    agent_id: str
    agent_name: str
    team_name: str
    abort: AbortSignal
    leader: bool = False


_current: contextvars.ContextVar[AgentContext | None] = \
    contextvars.ContextVar('chatchat_agent_context', default=None)


def current_agent() -> AgentContext | None:
    return _current.get()


def spawn_task(ctx: AgentContext, coro, *, name: str = '') -> asyncio.Task:
    loop = asyncio.get_running_loop()

    async def _run():
        token = _current.set(ctx)
        try:
            return await coro
        finally:
            _current.reset(token)

    return loop.create_task(_run(), name=name)
