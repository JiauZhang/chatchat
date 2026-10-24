from __future__ import annotations


class HostTasks:
    """Background tasks the host owns, which the runtime's task tools reach.

    claude-code has one TaskOutput and one TaskStop, and both cover a
    background shell command and a sub-agent alike; the id says which. A host
    that can start long-running work of its own plugs in here, and the runtime
    reads and stops it the same way it reads its own agents - the returned block
    carries its own <task_kind>.
    """

    def has(self, task_id: str) -> bool:
        return False

    def read(self, task_id: str, *, block: bool = True, timeout_ms: int = 30_000):
        return None

    def stop(self, task_id: str) -> str:
        return ""
