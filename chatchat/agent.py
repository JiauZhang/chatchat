from .client import Client

class Agent:
    def __init__(
        self, *, name, description, client: Client, instruction=None, memory=None,
        generation_options={}, tools=None,
    ):
        self.client = client
        self.client.instruction = instruction
        self.name = name
        self.description = description
        self.tools = tools
        self.generation_options = generation_options
        self.memory = memory

    def __call__(self, message):
        return self.client.chat(message, generation_options=self.generation_options, tools=self.tools)

    def to_dict(self):
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'message': {
                            'type': 'string',
                            'description': 'Accurately and concisely state what you want it to do.',
                        }
                    },
                    'required': ['message'],
                }
            }
        }
