from __future__ import annotations
from dataclasses import dataclass, field
from queue import Queue, Empty
from threading import Thread, Event
from typing import Any
import asyncio


@dataclass
class ResourcePool:
    max_agents: int = 10
    max_teams: int = 5
    used_agents: int = 0
    used_teams: int = 0

    def can_spawn_agent(self) -> bool:
        return self.used_agents < self.max_agents

    def can_spawn_team(self) -> bool:
        return self.used_teams < self.max_teams


@dataclass
class Action:
    type: str
    payload: Any
    sender: str = ''
    metadata: dict = field(default_factory=dict)


class Actor:
    def __init__(self, *, name: str, event_bus):
        self._name = name
        self._bus = event_bus
        self._mailbox: Queue[tuple[Action, Queue | None]] = Queue()
        self._thread: Thread | None = None
        self._stop_event = Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    # === 公开执行入口 ===

    def chat(self, message: Any, action_type: str = 'chat') -> Any:
        """统一同步入口：走 mailbox。"""
        action = Action(type=action_type, payload=message)
        return self.run(action)

    async def achat(self, message: Any, action_type: str = 'chat') -> Any:
        """统一异步入口：走 mailbox。"""
        action = Action(type=action_type, payload=message)
        return await self.arun(action)

    def run(self, action: Action) -> Any:
        if self._thread is None:
            raise RuntimeError('Actor is not started. Call start() first.')
        reply_queue: Queue = Queue()
        self._mailbox.put((action, reply_queue))
        result = reply_queue.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def arun(self, action: Action) -> Any:
        return await asyncio.to_thread(self.run, action)

    def _run(self, action: Action) -> None:
        self._mailbox.put((action, None))

    async def _arun(self, action: Action) -> None:
        await asyncio.to_thread(self._mailbox.put, (action, None))

    # === 生命周期 ===

    def start(self):
        self._stop_event.clear()
        self._thread = Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    # === 内部机制 ===

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                action, reply_queue = self._mailbox.get(timeout=0.1)
                try:
                    result = self._on_message(action)
                    if reply_queue is not None:
                        reply_queue.put(result)
                except Exception as e:
                    if reply_queue is not None:
                        reply_queue.put(e)
            except Empty:
                continue

    def _on_message(self, action: Action) -> Any:
        raise NotImplementedError