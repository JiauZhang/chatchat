import json, os
from glob import glob
from functools import cache
from typing import Generator

from chatchat.client import Client
from chatchat.skill import Skill
from chatchat.tool import Tool, Tools
from chatchat.types import Message, ToolCall, ProgressType
from chatchat.hook import _HookEmitter


class Agent(_HookEmitter):
    def __init__(
        self, *, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None,
        http_options=None, max_depth=3,
    ):
        super().__init__()
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.http_options = http_options or {}
        self.name = name
        self.stream = stream
        self.thinking = thinking
        self.tools = Tools(*tools) if tools else None
        self.max_depth = max_depth
        self._depth = 0
        self.subagents = {}

        self.skills = []
        if skills:
            seen = set()
            for path in skills:
                for skill_md in glob(os.path.join(path, '**', 'SKILL.md'), recursive=True):
                    d = os.path.dirname(skill_md)
                    if d not in seen:
                        seen.add(d)
                        self.skills.append(Skill(d))

        self.client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )
        self._delegate_tool = self._build_delegate_tool()

    def _build_delegate_tool(self):
        skills_desc = ''
        if self.skills:
            names = [s.name for s in self.skills]
            skills_desc = f" Available skills: {', '.join(names)}."

        return Tool(
            name='delegate',
            description=(
                'Delegate a task to a sub-agent. '
                'The sub-agent works independently with its own LLM and tools, '
                'and returns the final result.'
                f'{skills_desc}'
            ),
            tool=self._handle_delegate,
            parameters={
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': (
                            'Name for the sub-agent. '
                            'Use an existing name to continue the same sub-agent '
                            '(its conversation history is preserved), '
                            'or a new name to create a fresh one.'
                        ),
                    },
                    'message': {
                        'type': 'string',
                        'description': 'The specific task to delegate.',
                    },
                    'instruction': {
                        'type': 'string',
                        'description': (
                            'Role description for the sub-agent, '
                            'e.g. "You are a researcher skilled at searching '
                            'and analyzing information."'
                        ),
                    },
                    'skill': {
                        'type': 'string',
                        'description': (
                            'Optional skill template name. '
                            'Using a skill is recommended for specialized tasks.'
                            f'{skills_desc}'
                        ),
                    },
                },
                'required': ['name', 'message'],
            },
        )

    @cache
    def _get_tools(self):
        if self.tools:
            return Tools(self._delegate_tool, *self.tools.tools)
        return Tools(self._delegate_tool)

    def _find_skill(self, name):
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    def _handle_delegate(self, name, message, instruction=None, skill=None):
        current_depth = getattr(self, '_depth', 0)
        if current_depth >= self.max_depth:
            return (
                f'Error: maximum delegation depth ({self.max_depth}) reached. '
                f'Cannot delegate "{name}".'
            )

        if skill:
            skill_obj = self._find_skill(skill)
            if not skill_obj:
                return f'Error: skill "{skill}" not found.'
            instruction = skill_obj.instruction

        if name in self.subagents:
            subagent = self.subagents[name]
        else:
            subagent = Agent(
                name=name,
                instruction=instruction,
                provider=self.provider,
                model=self.model,
                tools=list(self.tools.tools) if self.tools else None,
                skills=[s.source for s in self.skills] if self.skills else None,
                http_options=self.http_options,
                stream=self.stream,
                thinking=self.thinking,
                max_depth=self.max_depth,
            )
            subagent._depth = current_depth + 1
            self.subagents[name] = subagent
            self._bridge_events(subagent)

        result = subagent.chat(message)
        if isinstance(result, Generator):
            return ''.join(result)
        return result

    def _bridge_events(self, subagent):
        for h in self._start_handlers:
            subagent.on_start(h)
        for h in self._step_handlers:
            subagent.on_step(h)
        for h in self._end_handlers:
            subagent.on_end(h)
        for h in self._error_handlers:
            subagent.on_error(h)
        for h in self._interact_handlers:
            subagent.on_interact(h)

    def chat(self, message: str):
        self._emit(ProgressType.AGENT_START, name=self.name or '', data={'message': message})
        try:
            if self.stream:
                return self._stream_chat(self.client, message)
            return self._nonstream_chat(self.client, message)
        except Exception as e:
            self._emit(
                ProgressType.AGENT_ERROR, name=self.name or '',
                content=str(e), data={'error': str(e)},
            )
            raise

    def clear(self):
        self.client.clear()
        for subagent in self.subagents.values():
            subagent.clear()
        self.subagents.clear()

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        tool_results = []
        all_tools = self._get_tools()
        for tc in tool_calls:
            args = json.loads(tc.arguments)
            tool = all_tools[tc.name]
            result = tool(**args)
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _nonstream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            response = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self._get_tools(),
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '', data={'response': msg.content})
                return msg.content
            tool_results = self._execute_tool_calls(msg.tool_calls)
            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=round,
                data={'round': round, 'tool_calls': [{'name': tc.name, 'arguments': tc.arguments} for tc in msg.tool_calls]})
            new_messages = tool_results

    def _stream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        round = 0
        while True:
            round += 1
            stream = client.chat(
                new_messages, stream=self.stream, thinking=self.thinking,
                tools=self._get_tools(),
            )
            acc = Message()
            has_tool_calls = False
            for chunk in stream:
                acc.accumulate(chunk.choices[0].delta)
                if chunk.choices[0].delta.tool_calls:
                    has_tool_calls = True
                yield chunk.choices[0].delta.content or ''
            if not has_tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '', data={'response': acc.content})
                break
            tool_results = self._execute_tool_calls(acc.tool_calls)
            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=round,
                data={'round': round, 'tool_calls': [{'name': tc.name, 'arguments': tc.arguments} for tc in acc.tool_calls]})
            new_messages = tool_results

    def state_dict(self):
        return {
            'name': self.name,
            'instruction': self.instruction,
            'messages': self.client.messages,
            'config': {
                'provider': self.provider,
                'model': self.model,
                'max_depth': self.max_depth,
                'stream': self.stream,
                'thinking': self.thinking,
                'http_options': self.http_options,
            },
            'subagents': {
                name: agent.state_dict()
                for name, agent in self.subagents.items()
            },
        }

    def load_state_dict(self, state):
        self.client.messages = state['messages']
        for name, sub_state in state['subagents'].items():
            subagent = Agent.from_state_dict(sub_state)
            self.subagents[name] = subagent
            self._bridge_events(subagent)

    @classmethod
    def from_state_dict(cls, state, tools=None, skills=None):
        agent = cls(
            name=state['name'],
            instruction=state['instruction'],
            provider=state['config']['provider'],
            model=state['config']['model'],
            max_depth=state['config']['max_depth'],
            stream=state['config']['stream'],
            thinking=state['config']['thinking'],
            http_options=state['config']['http_options'],
            tools=tools,
            skills=skills,
        )
        agent.client.messages = state['messages']
        for name, sub_state in state['subagents'].items():
            subagent = cls.from_state_dict(sub_state)
            agent.subagents[name] = subagent
            agent._bridge_events(subagent)
        return agent