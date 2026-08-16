from __future__ import annotations
import threading
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Any, Callable

from chatchat.message import Message
from chatchat.runtime import get_runtime
from chatchat.tool import Tool, Tools
from chatchat.skill import Skills
from chatchat.agent_loop import AgentLoop
from chatchat.client import ClientConfig


@dataclass
class BaseAgentConfig(ClientConfig):
    name: str
    description: str = ''
    thinking: bool = False
    skills: list | None = None
    max_turns: int = 0
    source: str = 'user'
    background: bool = False


@dataclass
class AgentConfig(BaseAgentConfig):
    tools: list | None = None


class BaseAgent:
    def __init__(self, id: str):
        self.id = id
        self._runtime = get_runtime()
        self._mailbox = Queue()
        self._stop_event = threading.Event()
        self._task_completed = threading.Event()
        self._thread: threading.Thread | None = None
        self._sub_agents: dict[str, BaseAgent] = {}
        self._parent: str | None = None

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

    def _emit(self, topic: str, data=None):
        self._runtime.emit(topic, data, name=getattr(self, 'name', self.id))

    def handle_message(self, msg: Message) -> Any:
        raise NotImplementedError

    def create_sub_agent(self, config: AgentConfig) -> Agent:
        agent = create_agent(config)
        agent._parent = self.id
        self._sub_agents[config.name] = agent
        return agent

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
            except Empty:
                continue
            try:
                result = self.handle_message(msg)
                if result is not None:
                    self._runtime.reply(msg, result)
            except Exception as e:
                self._emit('agent:error', {'error': str(e)})
                self._runtime.reply(msg, f'error: {e}')
            finally:
                self._task_completed.set()


def create_agent(config: AgentConfig) -> Agent:
    agent = Agent(config)
    get_runtime().register(agent)
    if not config.background:
        agent.start()
    return agent


class Agent(BaseAgent):
    def __init__(self, config: AgentConfig):
        self.name = config.name
        self.description = config.description
        self.config = config
        self.kind = 'agent'
        super().__init__(config.name)

        self._setup_tools()
        self._setup_skills()
        self._setup_client()

        self._loop = AgentLoop(
            self.client, self.tools, self.config.max_turns,
            self.config.thinking, self.name,
        )
        self._pending_notifications: list[dict] = []
        self._hooks: dict[str, list[Callable]] = {
            'start': [],
            'step': [],
            'end': [],
            'error': [],
        }

    @property
    def provider(self) -> str | None:
        return self.config.provider

    @property
    def model(self) -> str | None:
        return self.config.model

    @property
    def thinking(self) -> bool:
        return self.config.thinking

    @property
    def http_options(self) -> dict:
        return self.config.http_options or {}

    @property
    def max_turns(self) -> int:
        return self.config.max_turns

    def _setup_tools(self):
        self.tools = None
        if self.config.tools:
            self.tools = Tools()
            for t in self.config.tools:
                self.add_tool(t)

    def _setup_skills(self):
        self.skills = Skills(self.config.skills) if self.config.skills else None
        instruction = self.config.instruction
        if self.skills:
            si = self.skills.instruction
            if si:
                instruction = f'{instruction}\n\n{si}' if instruction else si
        self.instruction = instruction

    def _setup_client(self):
        self.client = None
        if self.config.provider and self.config.model:
            from chatchat.client import Client
            self.client = Client(
                provider=self.config.provider,
                model=self.config.model,
                instruction=self.config.instruction,
                name=self.config.name,
                http_options=self.config.http_options,
            )

    def _emit_lifecycle(self, event: str, **data):
        for handler in self._hooks.get(event, []):
            try:
                handler(self, **data)
            except Exception:
                pass

    def on(self, event: str, handler: Callable):
        if event in self._hooks:
            self._hooks[event].append(handler)
        return self

    def _wait_for_background(self, timeout: float = None):
        for agent in list(self._sub_agents.values()):
            if agent.config.background:
                agent._task_completed.wait(timeout=timeout)

    def handle_message(self, msg: Message) -> Any:
        if msg.type == 'text':
            return self._handle_chat(msg.payload)
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

    def chat(self, message: str) -> str:
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
        self._runtime.send(Message(
            sender=self.id, recipient=self._parent,
            type='notification', subtype='task_complete',
            payload={
                'content': result,
                'agent_name': self.name,
                'description': self.description,
                'subtype': 'task_complete',
            },
        ))

    def _handle_chat(self, message: str) -> str:
        message = self._build_message_with_notifications(message)
        self._emit_lifecycle('start', message=message)
        self._emit('agent:start', {'message': message})
        if not self.client:
            self._emit('agent:error', {'error': 'No LLM client configured'})
            self._emit_lifecycle('error', error='No LLM client configured')
            return 'Error: No LLM client configured'
        try:
            result = self._loop.run(message)
            self._wait_for_background()
            self._emit_lifecycle('end', content=result)
            self._notify_parent(result)
            return result
        except Exception as e:
            self._emit('agent:error', {'error': str(e)})
            self._emit_lifecycle('error', error=str(e))
            raise

    def add_tool(self, tool: Tool):
        tool._name = self.name
        if self.tools is None:
            self.tools = Tools(tool)
        else:
            self.tools.add(tool)

    def clear(self):
        if self.client:
            self.client.clear()

    def state_dict(self) -> dict:
        return {
            'name': self.name,
            'instruction': self.instruction,
            'messages': self.client.messages if self.client else [],
            'config': {
                'provider': self.config.provider,
                'model': self.config.model,
                'thinking': self.config.thinking,
                'http_options': self.config.http_options,
                'max_turns': self.config.max_turns,
            },
        }

    def load_state_dict(self, state: dict):
        if self.client:
            self.client.messages = state.get('messages', [])

    @classmethod
    def from_state_dict(
        cls,
        state: dict,
        tools: list | None = None,
    ) -> Agent:
        config = AgentConfig(
            name=state['name'],
            instruction=state.get('instruction', ''),
            provider=state['config']['provider'],
            model=state['config']['model'],
            thinking=state['config'].get('thinking', False),
            http_options=state['config'].get('http_options', {}),
            max_turns=state['config'].get('max_turns', 0),
            tools=tools,
        )
        agent = Agent(config)
        agent.load_state_dict(state)
        return agent