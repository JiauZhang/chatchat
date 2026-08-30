from __future__ import annotations

import asyncio

from chatchat.core.event import Event
from chatchat.core.ids import current_loop, make_id


class Actor:
    def __init__(self, kind: str, ident: str | None = None, runtime=None):
        if runtime is None:
            raise ValueError('An actor must belong to a Runtime')
        self._runtime = runtime
        self.kind = kind
        self.id = ident or make_id()
        self._mailbox = asyncio.Queue()
        self._runtime.register_entity(self.id, self.kind, self._mailbox)
        self._runtime.register_spawn(self.id, self._ensure_loop_task)
        self._stop_event = asyncio.Event()
        self._task_completed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sub_agents: dict[str, Actor] = {}
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
        self._runtime.start()
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
        self._runtime.unregister_entity(self.id)

    async def _emit(self, topic: str, data=None):
        await self._runtime.publish(Event(
            topic=f'lifecycle:{self.kind}:{topic}',
            source=self.id,
            data=data or {},
        ))

    async def _process_loop(self):
        while not self._stop_event.is_set():
            get_task = asyncio.ensure_future(self._mailbox.get())
            stop_task = asyncio.ensure_future(self._stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (get_task, stop_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done and not get_task.cancelled():
                    ev = get_task.result()
                else:
                    if self._stop_event.is_set():
                        break
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
                        await self._runtime.reply(
                            ev, f'{type(e).__name__}: {e}', source=self.id)
                finally:
                    self.state = 'idle'
            finally:
                # asyncio.wait does not cancel unfinished futures: drop them
                # explicitly so pending tasks don't accumulate between turns.
                if not stop_task.done():
                    stop_task.cancel()
                if not get_task.done():
                    get_task.cancel()

    async def handle_message(self, ev: Event):
        raise NotImplementedError
