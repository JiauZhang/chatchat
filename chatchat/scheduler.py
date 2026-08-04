from __future__ import annotations
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any

from chatchat.message import ID, Message


class TimeoutError(Exception):
    pass


class Scheduler:
    def __init__(self):
        self._entities: dict[str, Any] = {}
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        self._pending_requests: dict[str, threading.Event] = {}
        self._pending_replies: dict[str, Message] = {}
        self._conditions: dict[str, threading.Event] = {}
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

    def publish(self, topic: str, msg: Message):
        with self._lock:
            subscribers = list(self._subscriptions.get(topic, set()))
            for uid in subscribers:
                entity = self._entities.get(uid)
                if entity:
                    entity._mailbox.put(msg)

    def subscribe(self, topic: str, entity_id: ID):
        with self._lock:
            self._subscriptions[topic].add(entity_id.uid)

    def unsubscribe(self, topic: str, entity_id: ID):
        with self._lock:
            self._subscriptions[topic].discard(entity_id.uid)

    def wait(self, condition: str, timeout: float | None = None):
        with self._lock:
            event = self._conditions.get(condition)
            if event is None:
                event = threading.Event()
                self._conditions[condition] = event
        event.wait(timeout=timeout)

    def notify(self, condition: str):
        with self._lock:
            event = self._conditions.pop(condition, None)
        if event:
            event.set()

    def create_agent(self, config) -> ID:
        from chatchat.worker import Worker
        worker = Worker(config, self)
        self.register(worker)
        worker.start()
        return worker.id

    def create_team(self, config) -> ID:
        from chatchat.team import Team
        team = Team(config, self)
        self.register(team)
        team.start()
        return team.id

    def lookup(self, entity_id: ID):
        with self._lock:
            return self._entities.get(entity_id.uid)

    def list_entities(self, kind: str = '') -> list[ID]:
        with self._lock:
            if kind:
                return [e.id for e in self._entities.values() if e.id.kind == kind]
            return list(self._entities.keys())

    def stop(self, entity_id: ID):
        entity = self.lookup(entity_id)
        if entity:
            entity.stop()
            self.unregister(entity_id)

    def shutdown(self):
        with self._lock:
            ids = list(self._entities.keys())
            for uid in ids:
                entity = self._entities.get(uid)
                if entity:
                    entity.stop()
            self._entities.clear()
            self._subscriptions.clear()
            self._pending_requests.clear()
            self._pending_replies.clear()
            self._conditions.clear()