import inspect
from dataclasses import dataclass
from typing import Any

from chatchat.exceptions import SubAgentError


@dataclass
class ToolContext:
    agent: Any


class Tool:
    def __init__(self, *, func, name, description, parameters=None):
        self.func = func
        self.name = name
        self.description = description
        self.parameters = parameters
        self._interact_handlers = []

    def on_interact(self, handler):
        self._interact_handlers.append(handler)
        return self

    def _ask(self, question='', metadata=None):
        for h in self._interact_handlers:
            reply = h(question, metadata or {})
            if reply is not None:
                return reply
        return None

    def to_dict(self):
        function = {
            'name': self.name,
            'description': self.description,
        }
        if self.parameters is not None:
            function['parameters'] = self.parameters
        return {'type': 'function', 'function': function}

    async def __call__(self, ctx: ToolContext = None, **kwargs):
        from chatchat.runtime import Event, get_runtime
        source = ctx.agent.name if ctx else self.name
        await get_runtime().publish(Event(
            topic='lifecycle:tool:start', source=source,
            data={'name': self.name, 'arguments': kwargs},
        ))
        try:
            result = self._run(ctx, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except SubAgentError:
            raise
        except Exception as e:
            await get_runtime().publish(Event(
                topic='lifecycle:tool:error', source=source,
                data={'name': self.name, 'error': str(e), 'arguments': kwargs},
            ))
            return f'Error calling tool {self.name}: {e}'
        await get_runtime().publish(Event(
            topic='lifecycle:tool:end', source=source,
            data={'name': self.name, 'result': result},
        ))
        return result

    def step(self, ctx=None, content: str = ''):
        from chatchat.runtime import Event, get_runtime
        source = ctx.agent.name if ctx else self.name
        get_runtime().publish_sync(Event(
            topic='lifecycle:tool:step', source=source,
            data={'name': self.name, 'content': content},
        ))

    def _run(self, ctx: ToolContext | None, **kwargs):
        if ctx is not None and 'ctx' in inspect.signature(self.func).parameters:
            kwargs = {'ctx': ctx, **kwargs}
        return self.func(**kwargs)


def tool(*, name, description, parameters=None, auto_register=False):
    def decorator(func):
        t = Tool(
            func=func, name=name, description=description,
            parameters=parameters,
        )
        if auto_register:
            get_registry().register(t)
        return t
    return decorator


class ToolRegistry:
    """Process-wide registry of every tool the framework knows about.
    Built-in tools and user-registered tools share the same register()
    entry point; built-ins are simply registered at runtime bootstrap."""

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


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry():
    global _registry
    _registry = None


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
