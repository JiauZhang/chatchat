from __future__ import annotations
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from chatchat.scheduler import Scheduler


@dataclass
class Event:
    topic: str
    data: dict
    name: str = ''
    timestamp: float = field(default_factory=time.time)


class EventBus:
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    def on(self, topic: str, handler: Callable):
        with self._lock:
            self._listeners.setdefault(topic, []).append(handler)

    def off(self, topic: str, handler: Callable):
        with self._lock:
            self._listeners.get(topic, []).remove(handler)

    def emit(self, topic: str, data: dict = None, name: str = ''):
        ev = Event(topic=topic, data=data or {}, name=name)
        with self._lock:
            handlers = list(self._listeners.get(topic, []))
        for handler in handlers:
            try:
                handler(ev)
            except Exception:
                traceback.print_exc()


class Runtime:
    def __init__(self):
        self.scheduler = Scheduler()
        self.event_bus = EventBus()

    # -- Event API --
    def emit(self, topic: str, data: dict = None, name: str = ''):
        self.event_bus.emit(topic, data, name)

    def on(self, topic: str, handler: Callable):
        self.event_bus.on(topic, handler)

    def off(self, topic: str, handler: Callable):
        self.event_bus.off(topic, handler)

    # -- Message routing API --
    def send(self, msg):
        self.scheduler.send(msg)

    def request(self, msg, timeout: float = 30):
        return self.scheduler.request(msg, timeout)

    def reply(self, to_msg, payload):
        self.scheduler.reply(to_msg, payload)

    def register(self, entity):
        return self.scheduler.register(entity)

    def unregister(self, entity_id: str):
        self.scheduler.unregister(entity_id)

    def lookup(self, entity_id: str):
        return self.scheduler.lookup(entity_id)

    def lookup_by_name(self, name: str):
        return self.scheduler.lookup_by_name(name)

    def list_entities(self, kind: str = '') -> list[str]:
        return self.scheduler.list_entities(kind)

    def shutdown(self):
        self.scheduler.shutdown()

    # -- Event logging helpers --
    def enable_logging(self, *categories):
        if not categories:
            categories = ('client', 'tool', 'agent')
        for cat in categories:
            if cat == 'client':
                self.on('client:start', _on_client_start)
                self.on('client:step', _on_client_step)
                self.on('client:end', _on_client_end)
                self.on('client:error', _on_client_error)
            elif cat == 'tool':
                self.on('tool:start', _on_tool_start)
                self.on('tool:step', _on_tool_step)
                self.on('tool:end', _on_tool_end)
                self.on('tool:error', _on_tool_error)
            elif cat == 'agent':
                self.on('agent:start', _on_agent_start)
                self.on('agent:step', _on_agent_step)
                self.on('agent:end', _on_agent_end)
                self.on('agent:error', _on_agent_error)


# -- Default logging handlers --

def _on_client_start(ev: Event):
    print(f'[{ev.name:<10}  {"client:start":>12}] LLM request started')


def _on_client_step(ev: Event):
    choices = ev.data.get('choices', [])
    if choices:
        delta = choices[0].delta
        if delta.reasoning_content:
            print(delta.reasoning_content, end='', flush=True)
        elif delta.content:
            print(delta.content, end='', flush=True)
        elif delta.tool_calls:
            for tc in delta.tool_calls:
                if tc.arguments:
                    print(tc.arguments, end='', flush=True)


def _on_client_end(ev: Event):
    print(f'\n[{ev.name:<10}  {"client:end":>12}] LLM response complete')


def _on_client_error(ev: Event):
    error = ev.data.get('error', '')
    print(f'[{ev.name:<10}  {"client:error":>12}] {error}')


def _on_tool_start(ev: Event):
    print(f'[{ev.name:<10}  {"tool:start":>12}] {ev.data.get("name","")}')


def _on_tool_step(ev: Event):
    print(f'[{ev.name:<10}  {"tool:step":>12}] {ev.data.get("content","")}')


def _on_tool_end(ev: Event):
    print(f'[{ev.name:<10}  {"tool:end":>12}] {ev.data.get("name","")}')


def _on_tool_error(ev: Event):
    print(f'[{ev.name:<10}  {"tool:error":>12}] {ev.data.get("name","")}: {ev.data.get("error","")}')


def _on_agent_start(ev: Event):
    print(f'[{ev.name:<10}  {"agent:start":>12}] {ev.data.get("message","")}')


def _on_agent_step(ev: Event):
    tcs = ev.data.get('tool_calls', [])
    if tcs:
        names = [tc['name'] for tc in tcs]
        arys = [tc.get('arguments', '') for tc in tcs]
        print(f'[{ev.name:<10}  {"agent:step":>12}] {names} {arys}')


def _on_agent_end(ev: Event):
    print(f'[{ev.name:<10}  {"agent:end":>12}] {ev.data.get("content","")}')


def _on_agent_error(ev: Event):
    print(f'[{ev.name:<10}  {"agent:error":>12}] {ev.data.get("error","")}')


# -- Default runtime (module-level singleton, not thread-local) --
# Using a module-level instance ensures events from all threads
# go to the same runtime where handlers are registered.
# Tests can use set_runtime() to override for isolation.

_default_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = Runtime()
    return _default_runtime


def set_runtime(runtime: Runtime):
    global _default_runtime
    _default_runtime = runtime