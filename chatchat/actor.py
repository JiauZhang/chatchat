from __future__ import annotations

import asyncio

from chatchat.runtime import Event, current_loop, get_runtime, make_id


class Actor:
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind
        self.id = make_id()
        self._runtime = get_runtime()
        self._mailbox = asyncio.Queue()
        self._runtime.register_entity(self.id, self.kind, self._mailbox, name=self.name)
        self._runtime.register_spawn(self.id, self._ensure_loop_task)
        self._stop_event = asyncio.Event()
        self._task_completed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sub_agents: dict[str, Actor] = {}
        self._parent: str | None = None
        self._depth = 0
        self.state = 'idle'

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def sub_agents(self) -> dict[str, 'Actor']:
        return self._sub_agents

    def start(self):
        self._stop_event.clear()
        self._ensure_loop_task()

    def _ensure_loop_task(self):
        if self._task is not None and not self._task.done():
            return
        loop = current_loop()
        if loop is not None:
            self._task = loop.create_task(self._process_loop())

    async def stop(self, timeout: float = 2.0):
        for agent in list(self._sub_agents.values()):
            await agent.stop(timeout=timeout)
        self._stop_event.set()
        task = self._task
        self._task = None
        if task:
            try:
                await asyncio.wait_for(task, timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

    async def _emit(self, topic: str, data=None):
        await self._runtime.publish(Event(
            topic=f'lifecycle:{self.kind}:{topic}',
            source=self.name,
            data=data or {},
        ))

    async def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                ev = await asyncio.wait_for(self._mailbox.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            self.state = 'busy'
            try:
                result = await self.handle_message(ev)
                if result is not None and ev.reply_to:
                    await self._runtime.reply(ev, result, source=self.id)
            except asyncio.CancelledError:
                self.state = 'idle'
                raise
            except Exception as e:
                if ev.reply_to:
                    await self._runtime.reply(ev, e, source=self.id)
            finally:
                self.state = 'idle'

    async def handle_message(self, ev: Event):
        raise NotImplementedError