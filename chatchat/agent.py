import json
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
            for path in skills:
                self.skills.append(Skill(path))

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

    def _get_tools(self):
        """Tools including the built-in delegate tool, for LLM to see."""
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
            sub_agent = self.subagents[name]
            if instruction and instruction != sub_agent.instruction:
                return (
                    f'Error: cannot change instruction of existing '
                    f'sub-agent "{name}". Use a different name to create a new one.'
                )
        else:
            sub_agent = Agent(
                name=name,
                instruction=instruction,
                provider=self.provider,
                model=self.model,
                tools=list(self.tools.tools) if self.tools else None,
                http_options=self.http_options,
                stream=self.stream,
                thinking=self.thinking,
                max_depth=self.max_depth,
            )
            sub_agent._depth = current_depth + 1
            self.subagents[name] = sub_agent
            self._bridge_events(sub_agent)

        return sub_agent._chat(message)

    def _bridge_events(self, sub_agent):
        """Bridge sub-agent progress events to parent's handlers."""
        for h in self._start_handlers:
            sub_agent.on_start(h)
        for h in self._step_handlers:
            sub_agent.on_step(h)
        for h in self._end_handlers:
            sub_agent.on_end(h)
        for h in self._error_handlers:
            sub_agent.on_error(h)

    def _chat(self, message: str) -> str:
        """Internal chat that always returns a string result."""
        result = self.chat(message)
        if isinstance(result, Generator):
            return ''.join(result)
        return result

    def chat(self, message: str):
        try:
            return self._chat_with_tools(self.client, message)
        except Exception as e:
            self._emit(
                ProgressType.AGENT_ERROR, name=self.name or '',
                content=str(e), data={'error': str(e)},
            )
            raise

    def clear(self):
        self.client.clear()
        for sub_agent in self.subagents.values():
            sub_agent.clear()
        self.subagents.clear()

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        tool_results = []
        for tc in tool_calls:
            args = json.loads(tc.arguments)
            if tc.name == 'delegate':
                result = self._handle_delegate(**args)
            else:
                tool = self.tools[tc.name]
                result = tool(**args)
            tool_results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return tool_results

    def _chat_with_tools(self, client, text):
        self._emit(ProgressType.AGENT_START, name=self.name or '', data={'message': text})
        if self.stream:
            return self._stream_chat(client, text)
        return self._nonstream_chat(client, text)

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
        """Load state into this agent instance. Does not modify config."""
        self.client.messages = state['messages']
        for name, sub_state in state['subagents'].items():
            sub_agent = Agent.from_state_dict(sub_state)
            self.subagents[name] = sub_agent
            self._bridge_events(sub_agent)

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
            sub_agent = cls.from_state_dict(sub_state)
            agent.subagents[name] = sub_agent
            agent._bridge_events(sub_agent)
        return agent