from __future__ import annotations
import threading
import traceback
from queue import Queue, Empty
from typing import Any, Callable

from chatchat.message import Message


class TimeoutError(Exception):
    pass


_event_listeners: dict[str, list[Callable]] = {}


def on_event(topic: str, handler: Callable):
    _event_listeners.setdefault(topic, []).append(handler)


def off_event(topic: str, handler: Callable):
    _event_listeners.get(topic, []).remove(handler)


def emit_event(topic: str, data: dict = None):
    for handler in _event_listeners.get(topic, []):
        try:
            handler(topic, data or {})
        except Exception:
            traceback.print_exc()


def _on_client_start(topic, data):
    source = data.get('_source', '')
    print(f'[client:start  {source:>10}] LLM request started')


def _on_client_step(topic, data):
    choices = data.get('choices', [])
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


def _on_client_end(topic, data):
    source = data.get('_source', '')
    print(f'\n[client:end   {source:>10}] LLM response complete')


def _on_client_error(topic, data):
    source = data.get('_source', '')
    error = data.get('error', '')
    print(f'[client:error {source:>10}] {error}')


def _on_tool_start(topic, data):
    print(f'[tool:start   {data.get("_source",""):>10}] {data.get("name","")}')


def _on_tool_step(topic, data):
    print(f'[tool:step    {data.get("_source",""):>10}] {data.get("content","")}')


def _on_tool_end(topic, data):
    print(f'[tool:end     {data.get("_source",""):>10}] {data.get("name","")}')


def _on_tool_error(topic, data):
    s = data.get('_source', '')
    print(f'[tool:error   {s:>10}] {data.get("name","")}: {data.get("error","")}')


def _on_agent_start(topic, data):
    print(f'[agent:start  {data.get("_source",""):>10}] {data.get("message","")}')


def _on_agent_step(topic, data):
    source = data.get('_source', '')
    tcs = data.get('tool_calls', [])
    if tcs:
        names = [tc['name'] for tc in tcs]
        arys = [tc.get('arguments', '') for tc in tcs]
        print(f'[agent:step   {source:>10}] {names} {arys}')


def _on_agent_end(topic, data):
    print(f'[agent:end    {data.get("_source",""):>10}] {data.get("content","")}')


def _on_agent_error(topic, data):
    s = data.get('_source', '')
    print(f'[agent:error  {s:>10}] {data.get("error","")}')


def enable_event_logging(*categories):
    if not categories:
        categories = ('client', 'tool', 'agent')
    for cat in categories:
        if cat == 'client':
            on_event('client:start', _on_client_start)
            on_event('client:step', _on_client_step)
            on_event('client:end', _on_client_end)
            on_event('client:error', _on_client_error)
        elif cat == 'tool':
            on_event('tool:start', _on_tool_start)
            on_event('tool:step', _on_tool_step)
            on_event('tool:end', _on_tool_end)
            on_event('tool:error', _on_tool_error)
        elif cat == 'agent':
            on_event('agent:start', _on_agent_start)
            on_event('agent:step', _on_agent_step)
            on_event('agent:end', _on_agent_end)
            on_event('agent:error', _on_agent_error)


class Scheduler:
    def __init__(self):
        self._entities: dict[str, Any] = {}
        self._pending_requests: dict[str, threading.Event] = {}
        self._pending_replies: dict[str, Message] = {}
        self._lock = threading.Lock()

    def register(self, entity) -> str:
        with self._lock:
            self._entities[entity.id] = entity
        return entity.id

    def unregister(self, entity_id: str):
        with self._lock:
            self._entities.pop(entity_id, None)

    def send(self, msg: Message):
        with self._lock:
            entity = self._entities.get(msg.recipient)
            if entity:
                entity._mailbox.put(msg)

    def request(self, msg: Message, timeout: float = 30) -> Message:
        event = threading.Event()
        with self._lock:
            self._pending_requests[msg.id] = event
            entity = self._entities.get(msg.recipient)
            if not entity:
                self._pending_requests.pop(msg.id, None)
                raise ValueError(f'Unknown recipient: {msg.recipient}')
            entity._mailbox.put(msg)
        event.wait(timeout=timeout)
        with self._lock:
            self._pending_requests.pop(msg.id, None)
            reply = self._pending_replies.pop(msg.id, None)
        if reply is None:
            raise TimeoutError(f'Timeout waiting for reply ({timeout}s)')
        return reply

    def reply(self, to_msg: Message, payload: Any):
        reply = Message(
            sender=to_msg.recipient,
            recipient=to_msg.sender,
            type='reply',
            reply_to=to_msg.id,
            payload=payload,
        )
        with self._lock:
            event = self._pending_requests.get(to_msg.id)
            if event:
                self._pending_replies[to_msg.id] = reply
                event.set()

    def lookup(self, entity_id: str):
        with self._lock:
            return self._entities.get(entity_id)

    def lookup_by_name(self, name: str):
        with self._lock:
            for entity in self._entities.values():
                if entity.id == name:
                    return entity
        return None

    def list_entities(self, kind: str = '') -> list[str]:
        with self._lock:
            if kind:
                return [e.id for e in self._entities.values() if getattr(e, 'kind', '') == kind]
            return [e.id for e in self._entities.values()]

    def shutdown(self):
        with self._lock:
            ids = list(self._entities.keys())
            for uid in ids:
                entity = self._entities.get(uid)
                if entity:
                    entity.stop()
            self._entities.clear()
            self._pending_requests.clear()
            self._pending_replies.clear()