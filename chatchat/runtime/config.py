from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from chatchat.runtime.thinking import Thinking

DEFAULT_COMPACT_RESERVE = 40_000


@dataclass(frozen=True)
class ModelConfig:
    """Which model to talk to and how a client for it is made."""

    name: str | None = None
    thinking: Thinking | None = None
    client: object | None = None
    client_factory: Callable | None = None
    http_options: dict = field(default_factory=dict)
    protocols: dict | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """Everything a runtime needs at construction time."""

    instruction: str = ""
    model: ModelConfig = field(default_factory=ModelConfig)

    tools: list | None = None
    tool_context: object | None = None
    skills: object | None = None
    agent_memory: object | None = None
    rules: object | None = None
    services: object | None = None
    hooks: bool = True

    model_timeout: float = 120.0
    model_retries: int = 2
    context_window: int = 0
    compact_reserve: int = DEFAULT_COMPACT_RESERVE

    tasks_dir: str | None = None
    sidechain_dir: str | None = None
    file_history_dir: str | None = None
