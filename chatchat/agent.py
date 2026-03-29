import os
from .client import Client
from .tool import Tools
from .skill import Skill
from glob import glob

class Agent:
    def __init__(
        self, *, provider, model, name=None, description=None, instruction=None, memory=None,
        generation_options={}, tools=None, skills=None, http_options={},
    ):
        self.client = Client(
            provider=provider, model=model, instruction=instruction,
            http_options=http_options,
        )
        self.name = name
        self.description = description
        self.generation_options = generation_options
        self.memory = memory

        if skills:
            md_skills = []
            for skill in skills:
                md_skills += glob(os.path.join(skill, '**/SKILL.md'), recursive=True)
            md_skills = [Skill(os.path.dirname(md_skill)) for md_skill in md_skills]
            tools = md_skills if tools is None else tools + md_skills

        self.tools = Tools(*tools) if tools else None

    def __call__(self, message):
        return self.client.chat(message, generation_options=self.generation_options, tools=self.tools)

    def to_dict(self):
        assert self.name and self.description
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

class SubAgent(Agent):
    def __call__(self, message):
        self.client.clear()
        return self.client.chat(message, generation_options=self.generation_options, tools=self.tools)
