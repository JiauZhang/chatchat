class Tool:
    def __init__(self, *, tool, name, description, parameters=None,
                 event_bus=None, source='unknown'):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.tool = tool
        self._bus = event_bus
        self._source = source
        self._interact_handlers = []

    def _emit(self, topic: str, data: dict = None):
        if self._bus:
            self._bus.emit(topic, data or {}, source=self._source)

    def __call__(self, **kwargs):
        self._emit('tool:start', {'name': self.name, 'arguments': kwargs})
        try:
            result = self.tool(**kwargs)
        except Exception as e:
            self._emit('tool:error', {'name': self.name, 'error': str(e), 'arguments': kwargs})
            return f'Error calling tool {self.name}: {e}'
        self._emit('tool:end', {'name': self.name, 'result': result})
        return result

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
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters or {'type': 'object', 'properties': {}},
            }
        }


def tool(*, name, description, parameters=None, event_bus=None):
    def decorator(func):
        return Tool(
            tool=func, name=name, description=description,
            parameters=parameters, event_bus=event_bus,
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
        return [t.to_dict() for t in self.tools]