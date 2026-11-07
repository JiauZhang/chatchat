from __future__ import annotations

from chatchat.enums import ValueStrEnum


class TaskStatus(ValueStrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskRunStatus(ValueStrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class TaskRunType(ValueStrEnum):
    IN_PROCESS_TEAMMATE = "in_process_teammate"


class TaskAction(ValueStrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


class ClaimReason(ValueStrEnum):
    TASK_NOT_FOUND = "task_not_found"
    ALREADY_CLAIMED = "already_claimed"
    ALREADY_RESOLVED = "already_resolved"
    BLOCKED = "blocked"
    AGENT_BUSY = "agent_busy"
