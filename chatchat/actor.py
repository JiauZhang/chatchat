from __future__ import annotations
from dataclasses import dataclass, field
from queue import Queue, Empty
from threading import Thread, Event
from typing import Any
import asyncio

from chatchat.task import Task, TaskStatus


def _process_dependency_completed(tasks, dep_notified, completed_task_id, handle_chat_fn):
    started = []
    for task_id, notified in list(dep_notified.items()):
        task = tasks.get(task_id)
        if not task:
            continue
        if completed_task_id in task.depends_on:
            notified.add(completed_task_id)
            if notified == set(task.depends_on):
                if task.status in (TaskStatus.ASSIGNED, TaskStatus.CREATED):
                    del dep_notified[task_id]
                    started.append(task_id)
                    handle_chat_fn(
                        f"你依赖的任务均已完成后，可以开始执行任务 {task_id}: {task.description}\n"
                        f"请使用工具执行此任务。"
                    )
    if started:
        return f"依赖任务 {completed_task_id} 已完成，已启动任务 {started}"
    return f"依赖任务 {completed_task_id} 已完成通知已收到。"


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
        self._tasks: dict[str, Task] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def chat(self, message: Any, action_type: str = 'chat') -> Any:
        action = Action(type=action_type, payload=message)
        return self.run(action)

    async def achat(self, message: Any, action_type: str = 'chat') -> Any:
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

    def start(self):
        self._stop_event.clear()
        self._thread = Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

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