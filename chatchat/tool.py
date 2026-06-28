import inspect

from chatchat.types import Progress


class Tool:
    def __init__(self, *, tool, name, description, parameters=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = tool

    def __call__(self, **kwargs):
        on_progress = kwargs.pop('on_progress', None)
        try:
            if on_progress and self._accepts_on_progress():
                result = self.tool(on_progress=on_progress, **kwargs)
            else:
                result = self.tool(**kwargs)
        except Exception as e:
            if on_progress:
                on_progress(Progress(
                    type=ProgressType.TOOL_ERROR, tool_name=self.name,
                    content=str(e),
                ))
            return f'call tool {self.name} failed.'
        return result

    def _accepts_on_progress(self):
        return 'on_progress' in inspect.signature(self.tool).parameters

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