class Tool:
    def __init__(self, *, tool, name, description, parameters=None, on_start=None, on_end=None, on_error=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = tool
        self.on_start = on_start
        self.on_end = on_end
        self.on_error = on_error

    def __call__(self, **kwargs):
        if self.on_start:
            self.on_start(self, **kwargs)
        try:
            tool_result = self.tool(**kwargs)
        except Exception as e:
            if self.on_error:
                self.on_error(self, e)
            return f'call tool {self.name} failed.'
        if self.on_end:
            self.on_end(self, tool_result)
        return tool_result

    def to_dict(self):
        parameters = {} if self.parameters is None else {'parameters': self.parameters}
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                **parameters,
            }
        }

def tool(*, name, description, parameters=None, on_start=None, on_end=None, on_error=None):
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

    def to_dict(self):
        tool_dicts = []
        for tool in self.tools:
            tool_dicts.append(tool.to_dict())
        return tool_dicts
