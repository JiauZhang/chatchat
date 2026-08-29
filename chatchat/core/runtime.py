from __future__ import annotations
import asyncio
import fnmatch
from typing import Any, Callable

from chatchat.core.event import Event, annotate, parse_topic
from chatchat.core.ids import make_id
from chatchat.core.logging import subscribe_logging
from chatchat.core.transport import close_transport


class RequestTimeoutError(Exception):
    pass


class Runtime:
    """A self-contained runtime: its own message router, tool table and tool
    handler, plus all lifecycle. Every agent/team must belong to a Runtime;
    there is no global default."""

    def __init__(self):
        from chatchat.agents.builtin_tools import ensure_builtin_tools
        from chatchat.core.tool_handler import ToolHandler
        from chatchat.tools.registry import ToolRegistry
        self._entities: dict[str, tuple[str, asyncio.Queue]] = {}
        self._spawners: dict[str, Callable] = {}
        self._observers: dict[str, list[Callable]] = {}
        self._pending_futures: dict[str, asyncio.Future] = {}
        self._logging_enabled: set[str] = set()
        self.registry = ToolRegistry()
        ensure_builtin_tools(self.registry)
        self._handler = ToolHandler(self)
        self._scanned: set = set()
        self.reply_ttl = 120.0
        self._scan_interval = 2.0
        self._scavenger: asyncio.Task | None = None
        self._started = False

    @property
    def handler(self):
        return self._handler

    def start(self):
        if not self._started:
            self._handler.start()
            self._start_scavenger()
            self._started = True

    def _start_scavenger(self):
        if self._scavenger is not None and not self._scavenger.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._scavenger = loop.create_task(self._scavenge())

    async def _scavenge(self):
        while True:
            await asyncio.sleep(self._scan_interval)
            for actor in list(self._scanned):
                actor._expire_replies()

    # ----- entity directory ------------------------------------------------
    def register_entity(self, entity_id: str, kind: str, mailbox: asyncio.Queue):
        if entity_id in self._entities:
            raise ValueError(f'Duplicate entity id: {entity_id}')
        self._entities[entity_id] = (kind, mailbox)

    def register_spawn(self, entity_id: str, spawn: Callable):
        self._spawners[entity_id] = spawn

    def unregister_entity(self, entity_id: str):
        self._entities.pop(entity_id, None)
        self._spawners.pop(entity_id, None)

    def lookup_entity(self, entity_id: str):
        return self._entities.get(entity_id)

    def lookup(self, target: str):
        entry = self._entities.get(target)
        return (target, entry) if entry else (None, None)

    def list_entities(self, kind: str = '') -> list[str]:
        if kind:
            return [eid for eid, (k, _) in self._entities.items() if k == kind]
        return list(self._entities.keys())

    # ----- observers -------------------------------------------------------
    def subscribe(self, pattern: str, handler: Callable):
        self._observers.setdefault(pattern, []).append(handler)

    def unsubscribe(self, pattern: str, handler: Callable):
        handlers = self._observers.get(pattern, [])
        if handler in handlers:
            handlers.remove(handler)

    # ----- messaging -------------------------------------------------------
    async def publish(self, event: Event):
        annotate(event)
        await self._deliver_to_entity(event)
        self._deliver_to_observers(event)
        self._resolve_pending(event)

    def publish_sync(self, event: Event):
        annotate(event)
        self._deliver_to_entity_sync(event)
        self._deliver_to_observers(event)
        self._resolve_pending(event)

    async def _deliver_to_entity(self, event: Event):
        _, eid, _, _ = parse_topic(event.topic)
        if not eid:
            return
        entry = self._entities.get(eid)
        if entry:
            await entry[1].put(event)
        spawn = self._spawners.get(eid)
        if spawn:
            spawn()

    def _deliver_to_entity_sync(self, event: Event):
        _, eid, _, _ = parse_topic(event.topic)
        if not eid:
            return
        entry = self._entities.get(eid)
        if entry:
            entry[1].put_nowait(event)
        spawn = self._spawners.get(eid)
        if spawn:
            spawn()

    def _deliver_to_observers(self, event: Event):
        for pattern, handlers in list(self._observers.items()):
            if fnmatch.fnmatch(event.topic, pattern):
                for handler in list(handlers):
                    try:
                        handler(event)
                    except Exception:
                        import traceback
                        traceback.print_exc()

    def _resolve_pending(self, event: Event):
        future = self._pending_futures.get(event.topic)
        if future and not future.done():
            future.set_result(event.data)

    async def request(self, source: str, target_id: str, topic: str, data: Any,
                      timeout: float = 30) -> Any:
        correlation_id = make_id() + make_id()
        reply_topic = f'entity:reply:{correlation_id}'
        ev = Event(topic=topic, source=source, data=data, reply_to=reply_topic)
        annotate(ev)
        entry = self._entities.get(target_id)
        if not entry:
            raise ValueError(f'Unknown target: {target_id}')
        future = asyncio.get_running_loop().create_future()
        self._pending_futures[reply_topic] = future
        try:
            await entry[1].put(ev)
            spawn = self._spawners.get(target_id)
            if spawn:
                spawn()
            self._deliver_to_observers(ev)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise RequestTimeoutError(f'Timeout waiting for reply ({timeout}s)') from None
        finally:
            self._pending_futures.pop(reply_topic, None)

    async def reply(self, event: Event, data: Any, source: str = ''):
        if not event.reply_to:
            return
        reply_ev = Event(topic=event.reply_to, source=source or event.source, data=data)
        await self.publish(reply_ev)

    # ----- lifecycle -------------------------------------------------------
    def enable_logging(self, *categories):
        subscribe_logging(self, categories)

    async def shutdown(self):
        await self._handler.stop()
        if self._scavenger is not None:
            self._scavenger.cancel()
            self._scavenger = None
        await close_transport()
        self._entities.clear()
        self._spawners.clear()
        self._observers.clear()
        self._pending_futures.clear()
        self._logging_enabled.clear()
        self._scanned.clear()
        self._started = False