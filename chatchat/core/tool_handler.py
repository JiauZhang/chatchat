from __future__ import annotations
import asyncio

from chatchat.core.event import Event
from chatchat.core.ids import current_loop


TOOLS_ENTITY_ID = '__tools__'


class ToolHandler:
    """Tool executor owned by a Runtime. Tool calls arrive as 'tool:call'
    events on the runtime bus; each call runs concurrently in its own task.
    Resolved tools come from the runtime's own registry."""

    def __init__(self, runtime: 'Runtime'):
        self._runtime = runtime
        self._mailbox: asyncio.Queue = asyncio.Queue()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        runtime.register_entity(TOOLS_ENTITY_ID, 'tool', self._mailbox)
        runtime.register_spawn(TOOLS_ENTITY_ID, self.start)

    @property
    def registry(self):
        return self._runtime.registry

    def start(self):
        if not self._stop.is_set() or self._task is None:
            self._stop.clear()
        if self._task is not None and not self._task.done():
            return
        loop = current_loop()
        if loop is not None:
            self._task = loop.create_task(self._process_loop())

    async def stop(self, timeout: float = 2.0):
        self._stop.set()
        task = self._task
        self._task = None
        if task:
            try:
                await asyncio.wait_for(task, timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._runtime.unregister_entity(TOOLS_ENTITY_ID)

    async def _process_loop(self):
        while not self._stop.is_set():
            get_task = asyncio.ensure_future(self._mailbox.get())
            stop_task = asyncio.ensure_future(self._stop.wait())
            try:
                done, _ = await asyncio.wait(
                    (get_task, stop_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done and not get_task.cancelled():
                    ev = get_task.result()
                else:
                    if self._stop.is_set():
                        break
                    continue
                if ev.type == 'tool' and ev.subtype == 'call':
                    asyncio.create_task(self._run_and_reply(ev))
            finally:
                # asyncio.wait does not cancel unfinished futures: drop them
                # explicitly so pending tasks don't accumulate between turns.
                if not stop_task.done():
                    stop_task.cancel()
                if not get_task.done():
                    get_task.cancel()

    async def _run_and_reply(self, ev: Event):
        data = ev.data or {}
        name = data.get('name')
        allowed = set(data.get('tools', []))
        tool = self.registry.resolve(name) if name else None
        if tool is None or (allowed and name not in allowed):
            await self._runtime.reply(ev, {
                'role': 'tool',
                'content': f'Error: unknown or disallowed tool "{name}"',
                'tool_call_id': data.get('tool_call_id'),
            }, source=TOOLS_ENTITY_ID)
            return
        try:
            result = await tool(ctx=data.get('ctx'), **data.get('arguments', {}))
        except Exception as e:
            result = f'Error calling tool "{name}": {e}'
        await self._runtime.reply(ev, {
            'role': 'tool',
            'content': str(result),
            'tool_call_id': data.get('tool_call_id'),
        }, source=TOOLS_ENTITY_ID)