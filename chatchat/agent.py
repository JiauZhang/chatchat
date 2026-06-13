import json
import os
import types
from glob import glob

from chatchat.client import Client
from chatchat.tool import Tools
from chatchat.skill import Skill
from chatchat.response import Message, ToolCall


class BaseAgent:
    def __init__(
        self, *, provider, model, name=None, description=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None, http_options=None,
    ):
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.http_options = http_options or {}
        self.name = name
        self.description = description
        self.stream = stream
        self.thinking = thinking
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
        self, *, provider, model, name, description, instruction=None,
        stream=True, thinking=False, tools=None, skills=None, http_options=None,
    ):
        super().__init__(
            provider=provider, model=model, name=name, description=description,
            instruction=instruction, stream=stream, thinking=thinking,
            tools=tools, skills=skills, http_options=http_options,
        )

        if self.skills:
            skill_agents = []
            for skill in skills:
                skill_agents += glob(os.path.join(skill, '**/SKILL.md'), recursive=True)
            skill_agents = [SubAgent.from_skill(self, Skill(os.path.dirname(md))) for md in skill_agents]
            tools = skill_agents if tools is None else tools + skill_agents

        self.tools = Tools(*tools) if tools else None
        self.client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )

    @staticmethod
    def from_skill(agent: 'BaseAgent', skill: Skill):
        return SubAgent(
            provider=agent.provider, model=agent.model,
            stream=agent.stream, thinking=agent.thinking,
            tools=agent.tools, http_options=agent.http_options,
            name=skill.name, instruction=skill.instruction,
            description=skill.description,
        )

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        tool_results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            args = json.loads(tc.arguments)
            result = tool(**args)
            if isinstance(result, types.GeneratorType):
                result = ''.join(result)
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _chat_with_tools(self, client, text):
        if self.stream:
            return self._stream_chat(client, text)
        return self._nonstream_chat(client, text)

    def _nonstream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            response = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking, tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                return msg.content
            tool_results = self._execute_tool_calls(msg.tool_calls)
            new_messages = tool_results

    def _stream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            stream = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking, tools=self.tools,
            )
            acc = Message()
            has_tool_calls = False
            for chunk in stream:
                acc.accumulate(chunk.choices[0].delta)
                if chunk.choices[0].delta.tool_calls:
                    has_tool_calls = True
                yield chunk.choices[0].delta.content or ''
            if not has_tool_calls:
                break
            tool_results = self._execute_tool_calls(acc.tool_calls)
            new_messages = tool_results

    def __call__(self, message):
        self.client.clear()
        return self._chat_with_tools(self.client, message)


class Agent(SubAgent):
    def __call__(self, message):
        return self._chat_with_tools(self.client, message)