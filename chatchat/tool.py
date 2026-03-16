class Tool:
    def __init__(self, *, tool, name, description, parameters=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = tool

    def __call__(self, **kwargs):
        return self.tool(**kwargs)

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

def tool(*, name, description, parameters):
    def decorator(func):
        return Tool(tool=func, name=name, description=description, parameters=parameters)
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
