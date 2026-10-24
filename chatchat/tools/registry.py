from __future__ import annotations

from chatchat.tool import Tool, ToolContext, describe_tools


class ToolRegistry:
    """The tools one team offers, and who wins when a name is taken twice.

    The runtime's own tools are the contract: a host that injects a tool with
    the same name as one of them gets its own copy ignored, because the model
    was told about the runtime's version. Everything else is appended as-is.
    """

    def __init__(self, own=(), injected=()):
        self.own = tuple(own)
        self.injected = tuple(injected)
        self._own_names = {tool.name for tool in self.own}

    def names(self) -> set[str]:
        return set(self._own_names) | {tool.name for tool in self.injected if tool.name not in self._own_names}

    def find_own(self, name: str) -> Tool | None:
        for tool in self.own:
            if tool.name == name:
                return tool
        return None

    def offered(self) -> list[Tool]:
        return list(self.own) + [tool for tool in self.injected if tool.name not in self._own_names]

    def schemas(self, context: ToolContext) -> list[dict]:
        return describe_tools(self.offered(), context)
