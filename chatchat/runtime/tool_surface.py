from __future__ import annotations

from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL, retries, schema_problem
from chatchat.tools.builtin import builtin_tools
from chatchat.tools.registry import ToolRegistry


class ToolSurface:
    """What a team can be asked to do, and what it owes back at the end.

    It owns three things the team was holding: the tools the host injected, the
    registry that decides what the model sees, and the structured answer the
    team must produce when a schema was set. The last one registers a hook so
    an agent cannot finish without filling it in, which is why the surface is
    told about the owner's hooks rather than reaching for them.
    """

    def __init__(self, *, owner, injected=()):
        self.owner = owner
        self.injected = list(injected or [])
        self.output_schema: dict | None = None
        self.structured_output: dict | None = None
        self._attempts = 0
        self._hook = None

    def registry(self) -> ToolRegistry:
        return ToolRegistry(builtin_tools(self.owner), self.injected)

    def schemas(self, context) -> list[dict]:
        return self.registry().schemas(context)

    def find_own(self, name: str):
        return self.registry().find_own(name)

    def provided(self) -> list:
        return list(self.injected)

    def set_output_schema(self, schema: dict) -> str:
        problem = schema_problem(schema)
        if problem:
            return problem
        self.output_schema = schema
        self.structured_output = None
        self._attempts = 0
        if self._hook is None:
            self._hook = self.owner.hooks.register(
                "Stop",
                "*",
                fn=self._output_is_missing,
                error_message=f"Call {STRUCTURED_OUTPUT_TOOL} now with your final answer in the required shape.",
            )
        return ""

    def _output_is_missing(self, request: dict) -> bool:
        if self.structured_output is not None:
            return True
        if self._attempts >= retries():
            return True
        self._attempts += 1
        return False
