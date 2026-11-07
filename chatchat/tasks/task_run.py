from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field

from chatchat.tasks.enums import TaskRunStatus, TaskRunType

_TASK_ID_PREFIX = {TaskRunType.IN_PROCESS_TEAMMATE: "t"}
_TASK_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

_TERMINAL = {TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.KILLED}


def is_terminal_task_status(status: str) -> bool:
    return status in _TERMINAL


def generate_task_id(task_type: TaskRunType | str) -> str:
    prefix = _TASK_ID_PREFIX.get(task_type, "x")
    return prefix + "".join(secrets.choice(_TASK_ID_ALPHABET) for _ in range(8))


@dataclass
class TaskRun:
    id: str
    type: TaskRunType
    agent_id: str
    status: TaskRunStatus = TaskRunStatus.PENDING
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    def set_terminal(self, status: TaskRunStatus) -> None:
        if self.terminal:
            return
        self.status = status
        self._event.set()

    @property
    def terminal(self) -> bool:
        return is_terminal_task_status(self.status)


async def wait_for_terminal(task: TaskRun, abort=None, timeout: float | None = None) -> str:
    if task.terminal:
        return task.status
    waiter = asyncio.create_task(task._event.wait())
    try:
        if abort is not None:
            done, _ = await asyncio.wait(
                (waiter, asyncio.shield(asyncio.create_task(abort.wait()))),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if abort.aborted:
                abort.check()
        else:
            await asyncio.wait((waiter,), timeout=timeout)
        if not task.terminal:
            raise asyncio.TimeoutError(f"task {task.id} not finished")
        return task.status
    finally:
        waiter.cancel()
