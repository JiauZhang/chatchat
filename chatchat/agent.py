import os
from .client import Client
from .tool import Tools
from .skill import Skill
from glob import glob

class BaseAgent:
    def __init__(
        self, *, provider, model, name, description, instruction=None, memory=None,
        generation_options={}, tools=None, skills=None, http_options={},
    ):
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.http_options = http_options
        self.name = name
        self.description = description
        self.generation_options = generation_options
        self.memory = memory
        self.tools = tools
        self.skills = skills

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

class SubAgent(BaseAgent):
    def __init__(
        self, *, provider, model, name, description, instruction=None, memory=None,
        generation_options={}, tools=None, skills=None, http_options={},
    ):
        super().__init__(
            provider=provider, model=model, name=name, description=description, instruction=instruction,
            memory=memory, generation_options=generation_options, tools=tools, skills=skills,
            http_options=http_options,
        )

        if self.skills:
            md_skills = []
            for skill in skills:
                md_skills += glob(os.path.join(skill, '**/SKILL.md'), recursive=True)
            md_skills = [SubAgent.from_skill(self, Skill(os.path.dirname(md_skill))) for md_skill in md_skills]
            tools = md_skills if tools is None else tools + md_skills

        self.tools = Tools(*tools) if tools else None

    def __call__(self, message):
        client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )
        return client.chat(message, generation_options=self.generation_options, tools=self.tools)

    @staticmethod
    def from_skill(agent: BaseAgent, skill: Skill):
        return SubAgent(
            provider=agent.provider, model=agent.model, generation_options=agent.generation_options,
            tools=agent.tools, http_options=agent.http_options,
            name=skill.name, instruction=skill.instruction, description=skill.description,
        )

class Agent(SubAgent):
    def __init__(
        self, *, provider, model, name=None, description=None, instruction=None, memory=None,
        generation_options={}, tools=None, skills=None, http_options={},
    ):
        super().__init__(
            provider=provider, model=model, name=name, description=description, instruction=instruction,
            memory=memory, generation_options=generation_options, tools=tools, skills=skills,
            http_options=http_options,
        )
        self.client = Client(
            provider=provider, model=model, instruction=instruction,
            http_options=http_options,
        )

    def __call__(self, message):
        return self.client.chat(message, generation_options=self.generation_options, tools=self.tools)

