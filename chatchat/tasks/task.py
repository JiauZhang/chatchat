from __future__ import annotations

import asyncio
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

TASK_TYPES = (
    'local_bash', 'local_agent', 'remote_agent', 'in_process_teammate',
    'local_workflow', 'monitor_mcp', 'dream',
)

TASK_STATUSES = ('pending', 'running', 'completed', 'failed', 'killed')

_TASK_ID_PREFIX = {
    'local_bash': 'b', 'local_agent': 'a', 'remote_agent': 'r',
    'in_process_teammate': 't', 'local_workflow': 'w', 'monitor_mcp': 'm',
    'dream': 'd',
}
_TASK_ID_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'


def is_terminal_task_status(status: str) -> bool:
    return status in ('completed', 'failed', 'killed')


def generate_task_id(task_type: str) -> str:
    prefix = _TASK_ID_PREFIX.get(task_type, 'x')
    return prefix + ''.join(
        secrets.choice(_TASK_ID_ALPHABET) for _ in range(8))


@dataclass
class Task:
    id: str
    type: str
    agent_id: str
    status: str = 'pending'
    description: str = ''
    abort: object = None
    cleanup: Callable[[], None] | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    notified: bool = False
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    def set_terminal(self, status: str) -> None:
        if is_terminal_task_status(self.status):
            return
        self.status = status
        self.end_time = time.time()
        self._event.set()

    @property
    def terminal(self) -> bool:
        return is_terminal_task_status(self.status)


async def wait_for_terminal(task: Task, abort=None, timeout: float | None = None) \
        -> str:
    if task.terminal:
        return task.status
    waiter = asyncio.create_task(task._event.wait())
    try:
        if abort is not None:
            done, _ = await asyncio.wait(
                (waiter, asyncio.shield(asyncio.create_task(abort.wait()))),
                timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if abort.aborted:
                abort.check()
        else:
            await asyncio.wait((waiter,), timeout=timeout)
        if not task.terminal:
            raise asyncio.TimeoutError(f'task {task.id} not finished')
        return task.status
    finally:
        waiter.cancel()


def rand_name(prefix: str) -> str:
    return f'{prefix}-{random.randint(1000, 9999)}'
