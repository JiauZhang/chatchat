import json
from typing import Generator

from chatchat.client import Client
from chatchat.skill import Skills
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall, ProgressType
from chatchat.hook import _HookEmitter


class Agent(_HookEmitter):
    def __init__(
        self, *, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None,
        http_options=None,
    ):
        super().__init__()
        self.provider = provider
        self.model = model
        self.name = name
        self.stream = stream
        self.thinking = thinking
        self.http_options = http_options or {}
        self.tools = Tools(*tools) if tools else None

        self.skills = Skills(skills) if skills else None
        if self.skills:
            instruction = self.skills.instruction if instruction is None else f'{instruction}\n\n{self.skills.instruction}'

        self.instruction = instruction
        self.client = Client(
            provider=self.provider, model=self.model, instruction=self.instruction,
            http_options=self.http_options,
        )

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

    def _nonstream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            response = client.chat(
                new_messages, stream=False, thinking=self.thinking,
                tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '', data={'response': msg.content})
                return msg.content

            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=0,
                data={'round': 0, 'tool_calls': [{'name': tc.name, 'arguments': tc.arguments} for tc in msg.tool_calls]})
            new_messages = [
                {'role': 'tool', 'content': self.tools[tc.name](**json.loads(tc.arguments)), 'tool_call_id': tc.id}
                for tc in msg.tool_calls
            ]

    def _stream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            stream = client.chat(
                new_messages, stream=True, thinking=self.thinking,
                tools=self.tools,
            )
            acc = Message()
            for chunk in stream:
                acc.accumulate(chunk.choices[0].delta)
                yield chunk.choices[0].delta.content or ''
            if not acc.tool_calls:
                self._emit(ProgressType.AGENT_END, name=self.name or '', data={'response': acc.content})
                break

            self._emit(ProgressType.AGENT_STEP, name=self.name or '', step=0,
                data={'round': 0, 'tool_calls': [{'name': tc.name, 'arguments': tc.arguments} for tc in acc.tool_calls]})
            new_messages = [
                {'role': 'tool', 'content': self.tools[tc.name](**json.loads(tc.arguments)), 'tool_call_id': tc.id}
                for tc in acc.tool_calls
            ]

    def state_dict(self):
        return {
            'name': self.name,
            'instruction': self.instruction,
            'messages': self.client.messages,
            'config': {
                'provider': self.provider,
                'model': self.model,
                'stream': self.stream,
                'thinking': self.thinking,
                'http_options': self.http_options,
            },
        }

    def load_state_dict(self, state):
        self.client.messages = state['messages']

    @classmethod
    def from_state_dict(cls, state, tools=None):
        return cls(
            name=state['name'], instruction=state['instruction'],
            provider=state['config']['provider'], model=state['config']['model'],
            stream=state['config']['stream'], thinking=state['config']['thinking'],
            http_options=state['config']['http_options'],
            tools=tools,
        )