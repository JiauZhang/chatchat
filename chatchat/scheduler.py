from __future__ import annotations
import threading
from queue import Queue, Empty
from typing import Any, Callable

from chatchat.message import ID, Message


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
            pass


class Scheduler:
    def __init__(self):
        self._entities: dict[str, Any] = {}
        self._pending_requests: dict[str, threading.Event] = {}
        self._pending_replies: dict[str, Message] = {}
        self._lock = threading.Lock()

    def register(self, entity) -> ID:
        with self._lock:
            self._entities[entity.id.uid] = entity
        return entity.id

    def unregister(self, entity_id: ID):
        with self._lock:
            self._entities.pop(entity_id.uid, None)

    def send(self, msg: Message):
        with self._lock:
            entity = self._entities.get(msg.recipient.uid)
            if entity:
                entity._mailbox.put(msg)

    def request(self, msg: Message, timeout: float = 30) -> Message:
        event = threading.Event()
        with self._lock:
            self._pending_requests[msg.id] = event
            entity = self._entities.get(msg.recipient.uid)
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

    def lookup(self, entity_id: ID):
        with self._lock:
            return self._entities.get(entity_id.uid)

    def lookup_by_name(self, name: str):
        with self._lock:
            for entity in self._entities.values():
                if entity.id.name == name:
                    return entity
        return None

    def list_entities(self, kind: str = '') -> list[ID]:
        with self._lock:
            if kind:
                return [e.id for e in self._entities.values() if e.id.kind == kind]
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