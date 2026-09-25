from __future__ import annotations

import asyncio
import logging

from chatchat.team.mailbox import (Mailbox, Message, format_teammate_batch,
                                   is_structured_protocol_message)

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 0.5


class InboxPoller:
    def __init__(self, inbox: Mailbox, queue: asyncio.Queue | None = None,
                 handlers: dict[str, callable] | None = None,
                 interval: float = DEFAULT_INTERVAL,
                 lead_name: str = 'team-lead',
                 on_enqueue: callable | None = None,
                 task_feed: callable | None = None):
        self.inbox = inbox
        self.queue = queue if queue is not None else asyncio.Queue()
        self.handlers = handlers or {}
        self.interval = interval
        self.lead_name = lead_name
        self.on_enqueue = on_enqueue
        self.task_feed = task_feed
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self):
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self):
        self._stop.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    async def poll_once(self) -> str | None:
        unread = self.inbox.unread()
        if unread:
            self.inbox.mark_all_read()
            kept = [m for m in unread if not self._route(m)]
            if kept:
                kept.sort(key=lambda m: 0 if m.from_ == self.lead_name else 1)
                return format_teammate_batch(kept)
        if self.task_feed is not None:
            return await self.task_feed()
        return None

    async def _loop(self):
        while not self._stop.is_set():
            await asyncio.sleep(self.interval)
            if self._stop.is_set():
                break
            try:
                text = await self.poll_once()
            except Exception:
                logger.exception('inbox poll failed; retrying next tick')
                continue
            if text is not None and self.queue is not None:
                if self.on_enqueue is not None:
                    self.on_enqueue()
                self.queue.put_nowait(text)

    def _route(self, m: Message) -> bool:
        ptype = is_structured_protocol_message(m.text)
        if ptype is None:
            return False
        handler = self.handlers.get(ptype)
        if handler is not None:
            asyncio.get_running_loop().call_soon(handler, m)
            return True
        return False
