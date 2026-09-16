from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolContext:
    cwd: Path


@dataclass
class ToolResult:
    text: str
    meta: dict | None = None


class Tool:

    def __init__(self, *, tool, name, description, parameters=None,
                 on_start=None, on_end=None, on_error=None):
        self.tool = tool
        self.name = name
        self.description = description
        self.parameters = parameters
        self.on_start = on_start
        self.on_end = on_end
        self.on_error = on_error

    def describe(self, context: ToolContext) -> str:
        if callable(self.description):
            return self.description(context)
        return self.description

    async def __call__(self, context: ToolContext, **kwargs):
        if self.on_start:
            self.on_start(self, **kwargs)
        try:
            result = self.tool(context, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            if self.on_error:
                self.on_error(self, e)
            raise
        if self.on_end:
            self.on_end(self, result)
        return result

    def to_dict(self, context: ToolContext):
        parameters = {} if self.parameters is None else {'parameters': self.parameters}
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.describe(context),
                **parameters,
            }
        }


def tool(*, name, description, parameters=None, on_start=None, on_end=None,
         on_error=None):
    def decorator(func):
        return Tool(
            tool=func, name=name, description=description, parameters=parameters,
            on_start=on_start, on_end=on_end, on_error=on_error,
        )
    return decorator


class Tools:

    def __init__(self, *tools: Tool):
        self.tools = tools
        self.name_to_tool = {}
        for tool in self.tools:
            self.name_to_tool[tool.name] = tool

    def __getitem__(self, name):
        return self.name_to_tool[name]

    def to_dict(self, context: ToolContext):
        return [tool.to_dict(context) for tool in self.tools]
