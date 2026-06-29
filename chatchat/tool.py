import inspect

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
        self._emit(ProgressType.TOOL_START, name=self.name)
        try:
            if self._accepts('on_step'):
                kwargs['on_step'] = lambda content='', step=0: self._emit(
                    ProgressType.TOOL_STEP, name=self.name,
                    content=content, step=step,
                )
            result = self.tool(**kwargs)
        except Exception as e:
            self._emit(
                ProgressType.TOOL_ERROR, name=self.name,
                content=str(e),
            )
            return f'call tool {self.name} failed.'
        self._emit(ProgressType.TOOL_END, name=self.name)
        return result

    def _accepts(self, param):
        return param in inspect.signature(self.tool).parameters

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

    def to_dict(self):
        tool_dicts = []
        for tool in self.tools:
            tool_dicts.append(tool.to_dict())
        return tool_dicts