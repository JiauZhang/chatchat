from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from chatchat.runtime.background_tasks import BackgroundTasks
from chatchat.runtime.sandbox import Sandbox


class UserInput(Protocol):
    def __call__(self, agent, questions: list[dict]) -> list[str]: ...


class ToolPolicy(Protocol):
    def __call__(self, request: dict) -> dict: ...


@dataclass
class RuntimeServices:
    """The capabilities a host hands to a runtime.

    They are dependencies, not session state: a policy or a sandbox provider is
    shared by every run in the process, while the conversation, roster and
    tasks belong to one runtime instance. A missing capability stays None so
    the runtime can expose only the tools it can actually honour.
    """

    user_input: UserInput | None = None
    tool_policy: ToolPolicy | None = None
    background_tasks: BackgroundTasks | None = None
    sandbox: Sandbox | None = None
