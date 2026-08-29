import inspect
from dataclasses import dataclass
from typing import Any

from chatchat.core.exceptions import SubAgentError


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
        from chatchat.core.event import Event
        source = getattr(getattr(ctx, 'agent', None), 'id', None) or self.name
        runtime = getattr(getattr(ctx, 'agent', None), '_runtime', None)
        if runtime is not None:
            await runtime.publish(Event(
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
            if runtime is not None:
                await runtime.publish(Event(
                    topic='lifecycle:tool:error', source=source,
                    data={'name': self.name, 'error': str(e), 'arguments': kwargs},
                ))
            return f'Error calling tool {self.name}: {e}'
        if runtime is not None:
            await runtime.publish(Event(
                topic='lifecycle:tool:end', source=source,
                data={'name': self.name, 'result': result},
            ))
        return result

    def step(self, ctx=None, content: str = ''):
        from chatchat.core.event import Event
        source = getattr(getattr(ctx, 'agent', None), 'id', None) or self.name
        runtime = getattr(getattr(ctx, 'agent', None), '_runtime', None)
        if runtime is not None:
            runtime.publish_sync(Event(
                topic='lifecycle:tool:step', source=source,
                data={'name': self.name, 'content': content},
            ))

    def _run(self, ctx: ToolContext | None, **kwargs):
        if ctx is not None and 'ctx' in inspect.signature(self.func).parameters:
            kwargs = {'ctx': ctx, **kwargs}
        return self.func(**kwargs)


def tool(*, name, description, parameters=None):
    def decorator(func):
        return Tool(
            func=func, name=name, description=description,
            parameters=parameters,
        )
    return decorator
