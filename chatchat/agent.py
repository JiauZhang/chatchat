import json
import os
import types
from glob import glob

from chatchat.client import Client
from chatchat.tool import Tools
from chatchat.skill import Skill
from chatchat.types import Message, ToolCall, Progress


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


class Agent(BaseAgent):
    def __init__(
        self, *, provider, model, name=None, description=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None, http_options=None,
    ):
        super().__init__(
            provider=provider, model=model, name=name, description=description,
            instruction=instruction, stream=stream, thinking=thinking,
            tools=tools, skills=skills, http_options=http_options,
        )

        if self.skills:
            skill_agents = []
            for skill in self.skills:
                skill_agents += glob(os.path.join(skill, '**/SKILL.md'), recursive=True)
            skill_agents = [Agent.from_skill(self, Skill(os.path.dirname(md))) for md in skill_agents]
            all_tools = skill_agents if self.tools is None else list(self.tools) + skill_agents
        else:
            all_tools = self.tools

        self.tools = Tools(*all_tools) if all_tools else None
        self.client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )

    @staticmethod
    def from_skill(agent: 'BaseAgent', skill: Skill):
        return Agent(
            provider=agent.provider, model=agent.model,
            stream=agent.stream, thinking=agent.thinking,
            tools=agent.tools, http_options=agent.http_options,
            name=skill.name, instruction=skill.instruction,
            description=skill.description,
        )

    def chat(self, message, reset=False, on_progress=None):
        """发送消息给 Agent。

        reset=True 时清空对话历史（stateless，适用于工具式调用）。
        on_progress 回调接收 Progress，用于实时追踪执行进度。
        """
        if reset:
            self.client.clear()
        return self._chat_with_tools(self.client, message, on_progress=on_progress)

    def to_tool(self):
        """把自己包装成 Tool，其他 Agent 可通过 tool 机制调用。"""
        from chatchat.tool import Tool

        agent = self

        def _call(**kwargs):
            on_progress = kwargs.pop('on_progress', None)
            message = kwargs.get('message', '')
            return agent.chat(message, on_progress=on_progress)

        return Tool(
            tool=_call,
            name=self.name or self.__class__.__name__,
            description=self.description or '',
            parameters={
                'type': 'object',
                'properties': {
                    'message': {
                        'type': 'string',
                        'description': 'Accurately and concisely state what you want it to do.',
                    }
                },
                'required': ['message'],
            }
        )

    def _execute_tool_calls(self, tool_calls: list[ToolCall], on_progress=None) -> list[dict]:
        tool_results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            args = json.loads(tc.arguments)
            if on_progress:
                on_progress(Progress(
                    type='tool_start', tool_name=tc.name,
                    agent=self.name or '',
                ))
            result = tool(**args, on_progress=on_progress)
            if isinstance(result, types.GeneratorType):
                result = ''.join(result)
            if on_progress:
                on_progress(Progress(
                    type='tool_end', tool_name=tc.name,
                    agent=self.name or '',
                ))
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _chat_with_tools(self, client, text, on_progress=None):
        if self.stream:
            return self._stream_chat(client, text, on_progress=on_progress)
        return self._nonstream_chat(client, text, on_progress=on_progress)

    def _nonstream_chat(self, client, text, on_progress=None):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            if on_progress:
                on_progress(Progress(
                    type='thinking', agent=self.name or '',
                    step=round,
                ))
            response = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking, tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                if on_progress:
                    on_progress(Progress(
                        type='complete', agent=self.name or '',
                    ))
                return msg.content
            if on_progress:
                on_progress(Progress(
                    type='step', agent=self.name or '',
                    step=round,
                ))
            tool_results = self._execute_tool_calls(msg.tool_calls, on_progress=on_progress)
            new_messages = tool_results

    def _stream_chat(self, client, text, on_progress=None):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            if on_progress:
                on_progress(Progress(
                    type='thinking', agent=self.name or '',
                    step=round,
                ))
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
                if on_progress:
                    on_progress(Progress(
                        type='complete', agent=self.name or '',
                    ))
                break
            if on_progress:
                on_progress(Progress(
                    type='step', agent=self.name or '',
                    step=round,
                ))
            tool_results = self._execute_tool_calls(acc.tool_calls, on_progress=on_progress)
            new_messages = tool_results

    def __call__(self, message, **kwargs):
        """保留向后兼容。等价于 chat(message)。"""
        on_progress = kwargs.get('on_progress')
        return self.chat(message, on_progress=on_progress)