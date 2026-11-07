from __future__ import annotations


class BackgroundTasks:
    """Background tasks the runtime can read and stop by id.

    A runtime that can start long-running work of its own plugs in here, and
    the task tools read and stop it the same way they read their own agents -
    the returned block carries its own <task_kind>.
    """

    def has(self, task_id: str) -> bool:
        return False

    def read(self, task_id: str, *, block: bool = True, timeout_ms: int = 30_000):
        return None

    def stop(self, task_id: str) -> str:
        return ""
