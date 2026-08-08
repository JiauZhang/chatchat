from __future__ import annotations
import json
import threading
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Any, Callable, Generator

from chatchat.message import ID, Message
from chatchat.scheduler import emit_event
from chatchat.tool import Tool, Tools
from chatchat.skill import Skills


@dataclass
class AgentConfig:
    name: str
    description: str = ''
    provider: str | None = None
    model: str | None = None
    instruction: str = ''
    stream: bool = True
    thinking: bool = False
    tools: list | None = None
    skills: list | None = None
    http_options: dict | None = None
    max_turns: int = 20
    max_depth: int = 5
    is_builtin: bool = False
    background: bool = False
    source: str = 'user'  # 'built-in' | 'user'


def create_agent(config: AgentConfig, scheduler) -> Agent:
    """Unified factory function for creating any agent."""
    agent = Agent(config, scheduler)
    scheduler.register(agent)
    if not config.background:
        agent.start()
    return agent


class Agent:
    def __init__(self, config: AgentConfig, scheduler):
        self.id = ID(uid=config.name, kind='agent', name=config.name)
        self.name = config.name
        self.description = config.description
        self.scheduler = scheduler
        self.config = config

        self._mailbox = Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._task_completed = threading.Event()

        self.provider = config.provider
        self.model = config.model
        self.stream = config.stream
        self.thinking = config.thinking
        self.http_options = config.http_options or {}
        self.max_turns = config.max_turns
        self.max_depth = config.max_depth
        self._depth = 0

        self.tools = Tools(*config.tools) if config.tools else None
        if self.tools:
            for t in self.tools:
                t._emit_fn = self._emit
                t._source = self.name
        self._inject_management_tools()

        self.skills = Skills(config.skills) if config.skills else None
        instruction = config.instruction
        if self.skills:
            si = self.skills.instruction
            if si:
                instruction = f'{instruction}\n\n{si}' if instruction else si
        self.instruction = instruction

        self.client = None
        if config.provider and config.model:
            from chatchat.client import Client
            self.client = Client(
                provider=self.provider, model=self.model,
                instruction=self.instruction, http_options=self.http_options,
                emit_fn=self._emit, source=self.name,
            )

        self._sub_agents: dict[str, Agent] = {}
        self._parent: ID | None = None
        self._pending_notifications: list[dict] = []
        self._interact_handlers = []
        self._step = 0
        self._hooks: dict[str, list[Callable]] = {
            'start': [],
            'step': [],
            'end': [],
            'error': [],
        }

    def _inject_management_tools(self):
        def _create_agent(name: str, instruction: str, description: str = '',
                          background: bool = False, provider: str = None,
                          model: str = None) -> str:
            if name in self._sub_agents:
                return f'error: agent "{name}" already exists'
            if self._depth >= self.max_depth:
                return f'error: max agent depth ({self.max_depth}) reached, cannot create more sub-agents'
            cfg = AgentConfig(
                name=name, description=description, instruction=instruction,
                provider=provider or self.provider, model=model or self.model,
                stream=self.stream, thinking=self.thinking,
                http_options=self.http_options, max_turns=self.max_turns,
                max_depth=self.max_depth,
                background=background, source='user',
            )
            agent = self.create_sub_agent(cfg)
            agent._depth = self._depth + 1
            if background:
                agent.start()
                self.scheduler.send(Message(
                    sender=self.id, recipient=agent.id,
                    type='text', payload=instruction,
                ))
                return f'Agent "{name}" started in background. You will be notified when it completes.'
            result = agent.chat(instruction)
            return f'[Agent "{name}" completed]\n{result}'

        def _send_message(to: str, message: str, blocking: bool = False) -> str:
            target = self.scheduler.lookup_by_name(to)
            if not target:
                return f'error: unknown agent "{to}"'
            msg = Message(
                sender=self.id, recipient=target.id,
                type='text', payload=message,
            )
            if blocking:
                try:
                    reply = self.scheduler.request(msg, timeout=60)
                    return f'reply from {to}: {reply.payload}'
                except Exception as e:
                    return f'error waiting for reply: {e}'
            self.scheduler.send(msg)
            return f'message sent to {to}'

        def _task_stop(name: str) -> str:
            if name not in self._sub_agents:
                return f'error: unknown sub-agent "{name}"'
            agent = self._sub_agents[name]
            agent.stop()
            self.scheduler.unregister(agent.id)
            del self._sub_agents[name]
            return f'agent "{name}" stopped'

        tool_defs = [
            Tool(
                name='create_agent',
                description='Create a sub-agent for delegated tasks. Use this when a task is independent enough to run separately, or when you need parallel work. For foreground (default), the result is returned immediately. For background, the agent runs asynchronously and you will be notified when it completes.',
                tool=_create_agent,
                parameters={
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string', 'description': 'Name for the sub-agent'},
                        'instruction': {'type': 'string', 'description': 'System prompt and task description for the sub-agent'},
                        'description': {'type': 'string', 'description': 'Brief description of what this sub-agent will do'},
                        'background': {'type': 'boolean', 'description': 'Run in background (default false). When true, the agent runs asynchronously and notifies you when complete.'},
                        'provider': {'type': 'string', 'description': 'Optional provider override'},
                        'model': {'type': 'string', 'description': 'Optional model override'},
                    },
                    'required': ['name', 'instruction'],
                },
            ),
            Tool(
                name='send_message',
                description='Send a message to a sub-agent and optionally wait for reply. Use this to continue a sub-agent with additional context or instructions.',
                tool=_send_message,
                parameters={
                    'type': 'object',
                    'properties': {
                        'to': {'type': 'string', 'description': 'Target agent name'},
                        'message': {'type': 'string', 'description': 'Message content'},
                        'blocking': {'type': 'boolean', 'description': 'Wait for reply (default false)'},
                    },
                    'required': ['to', 'message'],
                },
            ),
            Tool(
                name='task_stop',
                description='Stop a running sub-agent. Use this when a sub-agent is no longer needed or is going in the wrong direction.',
                tool=_task_stop,
                parameters={
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string', 'description': 'Name of the sub-agent to stop'},
                    },
                    'required': ['name'],
                },
            ),
        ]

        for t in tool_defs:
            self.add_tool(t)

    def _emit(self, topic: str, data: dict = None):
        d = dict(data or {})
        d['_source'] = self.name
        emit_event(topic, d)

    def _emit_lifecycle(self, event: str, **data):
        for handler in self._hooks.get(event, []):
            try:
                handler(self, **data)
            except Exception:
                pass

    def on(self, event: str, handler: Callable):
        """Register a lifecycle hook handler.
        Events: 'start', 'step', 'end', 'error'
        Handler signature: handler(agent, **data)
        """
        if event in self._hooks:
            self._hooks[event].append(handler)
        return self

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0):
        for agent in list(self._sub_agents.values()):
            agent.stop(timeout=timeout)
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _wait_for_background(self, timeout: float = None):
        """Wait for all background sub-agents to complete their current task."""
        for agent in list(self._sub_agents.values()):
            if agent.config.background:
                agent._task_completed.wait(timeout=timeout)

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
                if msg.type == 'signal' and msg.subtype == 'stop':
                    self._stop_event.set()
                    continue
                try:
                    result = self.handle_message(msg)
                    if result is not None:
                        self.scheduler.reply(msg, result)
                except Exception as e:
                    self._emit('agent:error', {'error': str(e)})
                    self.scheduler.reply(msg, f'error: {e}')
                finally:
                    self._task_completed.set()
            except Empty:
                continue

    def handle_message(self, msg: Message) -> Any:
        if msg.type == 'text':
            result = self._handle_chat(msg.payload)
            if isinstance(result, Generator):
                output = ''.join(result)
                self._wait_for_background()
                return output
            return result
        if msg.type == 'notification':
            self._pending_notifications.append(msg.payload)
            return None
        if msg.type == 'signal':
            return self._handle_signal(msg)
        if msg.type == 'request':
            return self._handle_request(msg)
        return None

    def _handle_signal(self, msg: Message) -> str:
        if msg.subtype == 'stop':
            self.stop()
            return 'stopped'
        return f'unknown signal: {msg.subtype}'

    def _handle_request(self, msg: Message) -> Any:
        if msg.subtype == 'ping':
            return 'pong'
        if msg.subtype == 'status':
            return {
                'name': self.name,
                'running': self.is_running,
                'has_client': self.client is not None,
                'sub_agent_count': len(self._sub_agents),
            }
        if msg.subtype == 'list_sub_agents':
            return {
                'sub_agents': list(self._sub_agents.keys()),
            }
        return None

    def chat(self, message: str) -> str | Generator[str, None, None]:
        return self._handle_chat(message)

    def _build_message_with_notifications(self, message: str) -> str:
        if not self._pending_notifications:
            return message
        parts = []
        for n in self._pending_notifications:
            if n.get('subtype') == 'task_complete':
                parts.append(
                    f'[Task Complete: {n.get("agent_name", "unknown")}]\n'
                    f'{n.get("content", "")}'
                )
            elif n.get('subtype') == 'task_error':
                parts.append(
                    f'[Task Error: {n.get("agent_name", "unknown")}]\n'
                    f'{n.get("error", "")}'
                )
            else:
                parts.append(str(n.get('content', '')))
        self._pending_notifications.clear()
        return '\n\n'.join(parts) + '\n\n' + message

    def _notify_parent(self, result: str):
        if not self._parent:
            return
        self.scheduler.send(Message(
            sender=self.id, recipient=self._parent,
            type='notification', subtype='task_complete',
            payload={
                'content': result,
                'agent_name': self.name,
                'description': self.description,
                'subtype': 'task_complete',
            },
        ))

    def _handle_chat(self, message: str) -> str | Generator[str, None, None]:
        self._step = 0
        message = self._build_message_with_notifications(message)
        self._emit_lifecycle('start', message=message)
        self._emit('agent:start', {'message': message})
        if not self.client:
            self._emit('agent:error', {'error': 'No LLM client configured'})
            self._emit_lifecycle('error', error='No LLM client configured')
            return 'Error: No LLM client configured'
        try:
            if self.stream:
                return self._stream_chat_with_notify(self.client, message)
            result = self._nonstream_chat(self.client, message)
            self._wait_for_background()
            self._emit_lifecycle('end', content=result)
            self._notify_parent(result)
            return result
        except Exception as e:
            self._emit('agent:error', {'error': str(e)})
            self._emit_lifecycle('error', error=str(e))
            raise

    def _stream_chat_with_notify(self, client, text: str) -> Generator[str, None, None]:
        gen = self._stream_chat(client, text)
        result = ''
        for chunk in gen:
            result += chunk or ''
            yield chunk
        self._emit_lifecycle('end', content=result)
        self._notify_parent(result)

    def _execute_tool_calls(self, tool_calls: list) -> list[dict]:
        self._step += 1
        self._emit('agent:step', {
            'step': self._step,
            'tool_calls': [
                {'name': tc.name, 'arguments': tc.arguments}
                for tc in tool_calls
            ],
        })
        results = []
        for tc in tool_calls:
            tool = self.tools[tc.name]
            decoder = json.JSONDecoder()
            kwargs, _ = decoder.raw_decode(tc.arguments)
            result = tool(**kwargs)
            if isinstance(result, Generator):
                result = ''.join(result)
            results.append({
                'role': 'tool',
                'content': result,
                'tool_call_id': tc.id,
            })
        self._emit_lifecycle('step', step=self._step, results=results)
        return results

    def _nonstream_chat(self, client, text: str) -> str:
        from chatchat.types import ToolCall
        new_messages = [{'role': 'user', 'content': text}]
        for _ in range(self.max_turns):
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

    def _stream_chat(self, client, text: str) -> Generator[str, None, None]:
        from chatchat.types import Message as AccMessage
        new_messages = [{'role': 'user', 'content': text}]
        while True:
            gen = client.chat(
                new_messages,
                stream=True,
                thinking=self.thinking,
                tools=self.tools,
            )
            acc = AccMessage()
            for chunk in gen:
                acc.accumulate(chunk.choices[0].delta)
                yield chunk.choices[0].delta.content or ''
            if not acc.tool_calls:
                self._emit('agent:end', {'content': acc.content})
                break
            new_messages = self._execute_tool_calls(acc.tool_calls)

    def add_tool(self, tool: Tool):
        tool._emit_fn = self._emit
        tool._source = self.name
        if self.tools is None:
            self.tools = Tools(tool)
        else:
            self.tools.name_to_tool[tool.name] = tool
            self.tools.tools = self.tools.tools + (tool,)

    def create_sub_agent(self, config: AgentConfig) -> Agent:
        agent = create_agent(config, self.scheduler)
        agent._parent = self.id
        self._sub_agents[config.name] = agent
        return agent

    def on_interact(self, handler):
        self._interact_handlers.append(handler)
        return self

    def _ask(self, question: str = '', metadata: dict | None = None):
        for h in self._interact_handlers:
            reply = h(question, metadata or {})
            if reply is not None:
                return reply
        return None

    def clear(self):
        if self.client:
            self.client.clear()

    def state_dict(self) -> dict:
        return {
            'name': self.name,
            'instruction': self.instruction,
            'messages': self.client.messages if self.client else [],
            'config': {
                'provider': self.provider,
                'model': self.model,
                'stream': self.stream,
                'thinking': self.thinking,
                'http_options': self.http_options,
                'max_turns': self.max_turns,
            },
        }

    def load_state_dict(self, state: dict):
        if self.client:
            self.client.messages = state.get('messages', [])

    @classmethod
    def from_state_dict(
        cls,
        state: dict,
        scheduler,
        tools: list | None = None,
    ) -> Agent:
        config = AgentConfig(
            name=state['name'],
            instruction=state.get('instruction', ''),
            provider=state['config']['provider'],
            model=state['config']['model'],
            stream=state['config'].get('stream', True),
            thinking=state['config'].get('thinking', False),
            http_options=state['config'].get('http_options', {}),
            max_turns=state['config'].get('max_turns', 20),
            tools=tools,
        )
        agent = Agent(config, scheduler)
        agent.load_state_dict(state)
        return agent