from chatchat.tools.base import Tool


class ToolRegistry:
    """An index of tools. Each Runtime owns one; tools are independent objects
    mounted into a runtime via registry.register(tool)."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def resolve(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def list(self) -> list[Tool]:
        return list(self._tools.values())


class Tools:
    def __init__(self, *tools):
        self.tools = list(tools)
        self.name_to_tool = {}
        for tool in self.tools:
            self.name_to_tool[tool.name] = tool

    def add(self, tool):
        self.tools.append(tool)
        self.name_to_tool[tool.name] = tool

    def __getitem__(self, name):
        return self.name_to_tool[name]

    def __contains__(self, name):
        return name in self.name_to_tool

    def __iter__(self):
        return iter(self.tools)

    def to_dict(self):
        return [t.to_dict() for t in self.tools]
