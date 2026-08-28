from __future__ import annotations
import asyncio
import fnmatch
import random
import string
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from chatchat.tool import get_registry
from chatchat.transport import close_transport


def make_id():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


class RequestTimeoutError(Exception):
    pass


def current_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


@dataclass
class Event:
    topic: str = ''
    source: str = ''
    data: Any = None
    reply_to: str = ''
    type: str = ''
    subtype: str = ''
    timestamp: float = field(default_factory=time.time)


def parse_topic(topic: str) -> tuple[str, str, str, str]:
    kind = eid = msg_type = subtype = ''
    parts = topic.split(':')
    if len(parts) >= 4 and parts[0] == 'entity':
        kind, eid, msg_type = parts[1], parts[2], parts[3]
        if len(parts) >= 5:
            subtype = parts[4]
    return kind, eid, msg_type, subtype


def _annotate(event: Event):
    _, _, event.type, event.subtype = parse_topic(event.topic)


class Scheduler:
    def __init__(self):
        self._entities: dict[str, tuple[str, asyncio.Queue]] = {}
        self._names: dict[str, str] = {}
        self._spawners: dict[str, Callable] = {}
        self._observers: dict[str, list[Callable]] = {}
        self._pending_futures: dict[str, asyncio.Future] = {}
        self._logging_enabled: set[str] = set()

    def register_entity(self, entity_id: str, kind: str, mailbox: asyncio.Queue, name: str = ''):
        if entity_id in self._entities:
            raise ValueError(f'Duplicate entity id: {entity_id}')
        self._entities[entity_id] = (kind, mailbox)
        if name and name != entity_id:
            self._names[name] = entity_id

    def register_spawn(self, entity_id: str, spawn: Callable):
        self._spawners[entity_id] = spawn

    def unregister_entity(self, entity_id: str):
        self._entities.pop(entity_id, None)
        self._spawners.pop(entity_id, None)
        for name, eid in list(self._names.items()):
            if eid == entity_id:
                del self._names[name]

    def lookup_entity(self, entity_id: str):
        return self._entities.get(entity_id)

    def lookup(self, target: str):
        entry = self._entities.get(target)
        if entry:
            return target, entry
        eid = self._names.get(target)
        if eid:
            return eid, self._entities.get(eid)
        return None, None

    def list_entities(self, kind: str = '') -> list[str]:
        if kind:
            return [eid for eid, (k, _) in self._entities.items() if k == kind]
        return list(self._entities.keys())

    def subscribe(self, pattern: str, handler: Callable):
        self._observers.setdefault(pattern, []).append(handler)

    def unsubscribe(self, pattern: str, handler: Callable):
        handlers = self._observers.get(pattern, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event):
        _annotate(event)
        await self._deliver_to_entity(event)
        self._deliver_to_observers(event)
        self._resolve_pending(event)

    def publish_sync(self, event: Event):
        _annotate(event)
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
        _annotate(ev)
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

    def enable_logging(self, *categories):
        if not categories:
            categories = ('client', 'tool', 'agent')
        for cat in categories:
            if cat in self._logging_enabled:
                continue
            self._logging_enabled.add(cat)
            for pattern, handler in _LOG_HANDLERS.get(cat, []):
                self.subscribe(pattern, handler)

    async def shutdown(self):
        stop_tool_handler()
        await close_transport()
        self._entities.clear()
        self._names.clear()
        self._observers.clear()
        self._pending_futures.clear()
        self._logging_enabled.clear()


TOOLS_ENTITY_ID = '__tools__'

_tool_handler: 'ToolHandler | None' = None


class ToolHandler:
    """Owns tool execution for the whole framework. Tool calls arrive as
    'tool:call' events on the runtime bus; each call is run concurrently in its
    own task so multiple parallel tool calls from an agent loop stay parallel.
    The resolved tool instance comes from the shared ToolRegistry."""

    def __init__(self, runtime: Scheduler):
        self._runtime = runtime
        self._mailbox: asyncio.Queue = asyncio.Queue()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self):
        self._stop.clear()
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

    async def _process_loop(self):
        while not self._stop.is_set():
            try:
                ev = await asyncio.wait_for(self._mailbox.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if ev.type == 'tool' and ev.subtype == 'call':
                asyncio.create_task(self._run_and_reply(ev))

    async def _run_and_reply(self, ev: Event):
        data = ev.data or {}
        name = data.get('name')
        allowed = set(data.get('tools', []))
        tool = get_registry().resolve(name) if name else None
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


def ensure_builtin_tools():
    registry = get_registry()
    from chatchat.agent_tools import (
        create_agent_tool, send_message_tool, task_stop_tool,
    )
    from chatchat.team import create_team_tool
    for t in (create_agent_tool, create_team_tool, send_message_tool, task_stop_tool):
        if registry.resolve(t.name) is None:
            registry.register(t)


def start_tool_handler():
    global _tool_handler
    runtime = get_runtime()
    if TOOLS_ENTITY_ID in runtime._entities:
        return
    handler = ToolHandler(runtime)
    runtime.register_entity(TOOLS_ENTITY_ID, 'tool', handler._mailbox)
    runtime.register_spawn(TOOLS_ENTITY_ID, handler.start)
    handler.start()
    _tool_handler = handler
    ensure_builtin_tools()


def stop_tool_handler():
    global _tool_handler
    handler = _tool_handler
    _tool_handler = None
    if handler is not None:
        runtime = handler._runtime
        runtime.unregister_entity(TOOLS_ENTITY_ID)
        loop = current_loop()
        if loop is not None:
            loop.create_task(handler.stop())


def _tool_handler_clear():
    global _tool_handler
    _tool_handler = None


def _on_client_error(ev: Event):
    error = ev.data.get('error', '')
    print(f'[{ev.source:<10}  {"client:error":>12}] {error}')


def _on_client_retry(ev: Event):
    print(f'[{ev.source:<10}  {"client:retry":>12}] '
          f'retry {ev.data.get("retry","")}: {ev.data.get("error","")}')


def _tokens(ev: Event, tag: str):
    usage = ev.data.get('usage')
    if usage:
        print(f'[{ev.source:<10}  {tag:>12}] '
              f'prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}')


def _on_client_start(ev: Event):
    print(f'[{ev.source:<10}  {"client:start":>12}]')


def _on_client_end(ev: Event):
    print(f'[{ev.source:<10}  {"client:end":>12}]')


def _on_client_tokens(ev: Event):
    _tokens(ev, 'client:tokens')


def _on_tool_start(ev: Event):
    print(f'[{ev.source:<10}  {"tool:start":>12}]')


def _on_tool_step(ev: Event):
    print(f'[{ev.source:<10}  {"tool:step":>12}] {ev.data.get("content","")}')


def _on_tool_end(ev: Event):
    result = ev.data.get('result')
    result = '' if result is None else str(result)[:120]
    print(f'[{ev.source:<10}  {"tool:end":>12}] {result}')


def _on_tool_error(ev: Event):
    print(f'[{ev.source:<10}  {"tool:error":>12}] {ev.data.get("name","")}: {ev.data.get("error","")}')


def _on_agent_start(ev: Event):
    print(f'[{ev.source:<10}  {"agent:start":>12}] {ev.data.get("message","")}')


def _on_agent_step(ev: Event):
    if tcs := ev.data.get('tool_calls', []):
        print(f'[{ev.source:<10}  {"agent:step":>12}] {tcs}')


def _on_agent_end(ev: Event):
    print(f'[{ev.source:<10}  {"agent:end":>12}] {ev.data.get("content","")}')


def _on_agent_tokens(ev: Event):
    _tokens(ev, 'agent:tokens')


def _on_team_tokens(ev: Event):
    _tokens(ev, 'team:tokens')


def _on_agent_error(ev: Event):
    print(f'[{ev.source:<10}  {"agent:error":>12}] {ev.data.get("error","")}')


_LOG_HANDLERS = {
    'client': [
        ('lifecycle:client:start', _on_client_start),
        ('lifecycle:client:error', _on_client_error),
        ('lifecycle:client:retry', _on_client_retry),
        ('lifecycle:client:end', _on_client_end),
        ('lifecycle:client:tokens', _on_client_tokens),
    ],
    'tool': [
        ('lifecycle:tool:start', _on_tool_start),
        ('lifecycle:tool:step', _on_tool_step),
        ('lifecycle:tool:end', _on_tool_end),
        ('lifecycle:tool:error', _on_tool_error),
    ],
    'agent': [
        ('lifecycle:agent:start', _on_agent_start),
        ('lifecycle:agent:step', _on_agent_step),
        ('lifecycle:agent:end', _on_agent_end),
        ('lifecycle:agent:error', _on_agent_error),
        ('lifecycle:agent:tokens', _on_agent_tokens),
    ],
    'team': [
        ('lifecycle:team:start', _on_agent_start),
        ('lifecycle:team:step', _on_agent_step),
        ('lifecycle:team:end', _on_agent_end),
        ('lifecycle:team:error', _on_agent_error),
        ('lifecycle:team:tokens', _on_team_tokens),
    ],
}


_default_scheduler: Scheduler | None = None


def get_runtime() -> Scheduler:
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = Scheduler()
        start_tool_handler()
    return _default_scheduler


def set_runtime(scheduler: Scheduler):
    global _default_scheduler
    _default_scheduler = scheduler
