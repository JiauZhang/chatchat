from __future__ import annotations

from chatchat.enums import ValueStrEnum


class MemoryScope(ValueStrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class IdleReason(ValueStrEnum):
    AVAILABLE = "available"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class CompletionStatus(ValueStrEnum):
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    FAILED = "failed"


class SidechainStatus(ValueStrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageType(ValueStrEnum):
    TEXT = "text"
    IDLE_NOTIFICATION = "idle_notification"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_APPROVED = "shutdown_approved"
