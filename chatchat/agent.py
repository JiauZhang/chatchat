from .client import Client

class Agent:
    def __init__(self, client: Client, instruction):
        self.client = client
        self.client.instruction = instruction

    def __call__(self, text, *, generation_options={}, tools=None, memory=None):
        return self.client.chat(text, generation_options=generation_options, tools=tools)
