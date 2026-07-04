from chatchat.hook import _HookEmitter
from chatchat.types import ProgressType


class Tool(_HookEmitter):
    def __init__(self, *, tool, name, description, parameters=None):
        super().__init__()
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = tool

    def __call__(self, **kwargs):
        self._emit(
            ProgressType.TOOL_START, name=self.name,
            data={'arguments': kwargs},
        )
        try:
            result = self.tool(**kwargs)
        except Exception as e:
            self._emit(
                ProgressType.TOOL_ERROR, name=self.name,
                content=str(e), data={'error': str(e), 'arguments': kwargs},
            )
            return f'Error calling tool {self.name}: {e}'
        self._emit(
            ProgressType.TOOL_END, name=self.name,
            data={'result': result},
        )
        return result

    def to_dict(self):
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters or {'type': 'object', 'properties': {}},
            }
        }


def tool(*, name, description, parameters=None):
    def decorator(func):
        return Tool(
            tool=func, name=name, description=description, parameters=parameters,
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

    def __contains__(self, name):
        return name in self.name_to_tool

    def __iter__(self):
        return iter(self.tools)

    def to_dict(self):
        tool_dicts = []
        for tool in self.tools:
            tool_dicts.append(tool.to_dict())
        return tool_dicts