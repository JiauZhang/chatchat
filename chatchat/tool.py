class Tool:
    def __init__(self, *, name, description, parameters=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = None

    def __tool_call__(self, *args, **kwargs):
        return self.tool(**kwargs)

    def __class_call__(self, *args, **kwargs):
        self.tool = args[0]
        return self

    def __call__(self, *args, **kwargs):
        if self.tool is None:
            return self.__class_call__(*args, **kwargs)
        else:
            return self.__tool_call__(*args, **kwargs)

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

class Tools:
    def __init__(self, tools: list[Tool]):
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
