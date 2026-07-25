import json

from chatchat.client import Client
from chatchat.skill import Skills
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall
from chatchat.event import EventBus


class Agent:
    def __init__(
        self, *, event_bus, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None,
        http_options=None,
    ):
        self._bus = event_bus
        self.name = name or ''
        self._bus.source = self.name
        self.provider = provider
        self.model = model
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
            http_options=self.http_options, event_bus=self._bus,
        )

        if self.tools:
            for t in self.tools:
                t.set_event_bus(self._bus)

        self._interact_handlers = []
        self._step = 0

    def _emit(self, topic: str, data: dict = None):
        self._bus.emit(topic, data or {})

    def chat(self, message: str):
        self._step = 0
        self._emit('agent:start', {'message': message})
        try:
            if self.stream:
                return self._stream_chat(self.client, message)
            return self._nonstream_chat(self.client, message)
        except Exception as e:
            self._emit('agent:error', {'error': str(e)})
            raise

    def clear(self):
        self.client.clear()

    def on_interact(self, handler):
        self._interact_handlers.append(handler)
        return self

    def _ask(self, question='', metadata=None):
        for h in self._interact_handlers:
            reply = h(question, metadata or {})
            if reply is not None:
                return reply
        return None

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        self._step += 1
        self._emit('agent:step', {
            'step': self._step,
            'tool_calls': [{'name': tc.name, 'arguments': tc.arguments} for tc in tool_calls],
        })
        results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            result = tool(**json.loads(tc.arguments))
            results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        return results

    def _nonstream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            response = client.chat(
                new_messages, stream=False, thinking=self.thinking,
                tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                self._emit('agent:end', {'content': msg.content})
                return msg.content

            new_messages = self._execute_tool_calls(msg.tool_calls)

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
                self._emit('agent:end', {'content': acc.content})
                break

            new_messages = self._execute_tool_calls(acc.tool_calls)

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
    def from_state_dict(cls, state, event_bus, tools=None):
        agent = cls(
            event_bus=event_bus,
            name=state['name'], instruction=state['instruction'],
            provider=state['config']['provider'], model=state['config']['model'],
            stream=state['config']['stream'], thinking=state['config']['thinking'],
            http_options=state['config']['http_options'],
            tools=tools,
        )
        agent.load_state_dict(state)
        return agent