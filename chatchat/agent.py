from __future__ import annotations
import json
from dataclasses import dataclass

from chatchat.actor import Actor, Action, _process_dependency_completed
from chatchat.client import Client
from chatchat.skill import Skills
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall
from chatchat.event import EventBus
from chatchat.task import Task, TaskStatus


@dataclass
class AgentConfig:
    name: str
    provider: str | None = None
    model: str | None = None
    instruction: str = ''
    stream: bool = True
    thinking: bool = False
    tools: list | None = None
    skills: list | None = None
    http_options: dict | None = None


class Agent(Actor):
    def __init__(
        self, *, event_bus, provider, model, name=None, instruction=None,
        stream=True, thinking=False, tools=None, skills=None,
        http_options=None,
    ):
        actor_name = name or ''
        Actor.__init__(self, name=actor_name, event_bus=event_bus)
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
            http_options=self.http_options, event_bus=self._bus, source=self.name,
        )

        if self.tools:
            for t in self.tools:
                t._bus = self._bus
                t._source = self.name

        self._interact_handlers = []
        self._step = 0
        self._dep_notified: dict[str, set[str]] = {}

    def _emit(self, topic: str, data: dict = None):
        self._bus.emit(topic, data or {}, source=self.name)

    def start(self):
        Actor.start(self)

    def stop(self, timeout: float = 5.0):
        Actor.stop(self, timeout=timeout)

    def _on_message(self, action: Action) -> str:
        if action.type == 'task_assigned':
            task = action.payload
            self._tasks[task.id] = task
            if task.depends_on:
                for dep_id in task.depends_on:
                    dep = self._tasks.get(dep_id)
                    if not dep or dep.status != TaskStatus.COMPLETED:
                        self._dep_notified[task.id] = set()
                        return f"任务 {task.id} 已接收，依赖 {dep_id} 尚未完成，等待通知后自动执行。"
            return self._handle_chat(
                f"你被分配了一个新任务:\n"
                f"task_id: {task.id}\n"
                f"描述: {task.description}\n"
                f"请使用工具执行此任务。"
            )
        if action.type == 'dependency_completed':
            return _process_dependency_completed(
                self._tasks, self._dep_notified,
                action.payload.get('task_id', ''),
                self._handle_chat,
            )
        if action.type in ('chat', 'peer_message', 'meeting_call'):
            return self._handle_chat(action.payload)
        raise ValueError(f"Unknown action type: {action.type}")

    def _handle_chat(self, message: str) -> str:
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
        for _ in range(10):
            response = client.chat(
                new_messages,
                stream=False,
                thinking=self.thinking,
                tools=self.tools,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                self._emit('agent:end', {'content': msg.content})
                return msg.content

            new_messages = self._execute_tool_calls(msg.tool_calls)
        self._emit('agent:end', {'content': '已达到最大迭代次数'})
        return '已达到最大迭代次数'

    def _stream_chat(self, client, text):
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            gen = client.chat(
                new_messages,
                stream=True,
                thinking=self.thinking,
                tools=self.tools,
            )
            acc = Message()
            for chunk in gen:
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