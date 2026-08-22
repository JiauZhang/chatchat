from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Callable

from chatchat.actor import Actor
from chatchat.runtime import Event
from chatchat.tool import Tools
from chatchat.skill import Skills
from chatchat.agent_loop import AgentLoop
from chatchat.client import ClientConfig, create_client
from chatchat.types import Usage


@dataclass
class BaseAgentConfig(ClientConfig):
    name: str
    description: str = ''
    thinking: bool = False
    skills: list | None = None
    max_steps: int = 10
    source: str = 'user'
    background: bool = False
    max_depth: int = 5


@dataclass
class AgentConfig(BaseAgentConfig):
    tools: list | None = None


class Agent(Actor):
    def __init__(self, config: AgentConfig, kind: str = 'agent'):
        self.config = config
        self.description = config.description
        super().__init__(config.name, kind)
        self._setup_tools()
        self._setup_skills()
        self._setup_client()
        self._notifications: list[dict] = []
        self._lock = asyncio.Lock()
        self._usage = Usage()
        self._loop = AgentLoop(
            self.client, self.tools, config.max_steps, config.thinking, self.name,
            agent=self,
        )

    @property
    def provider(self):
        return self.config.provider

    @property
    def model(self):
        return self.config.model

    def _setup_tools(self):
        self.tools = None
        if tools := self._build_tools():
            self.tools = Tools(*tools)

    def _build_tools(self):
        return self.config.tools

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
            client_config = replace(self.config, instruction=self.instruction)
            self.client = create_client(client_config)

    async def stop(self, timeout: float = 2.0):
        await super().stop(timeout=timeout)
        if self.client:
            await self.client.close()

    async def handle_message(self, ev: Event) -> Any:
        if ev.type == 'text':
            return await self._handle_chat_locked(ev.data)
        if ev.type == 'notification':
            self._notifications.append(ev.data)
            return None
        if ev.type == 'signal':
            return await self._handle_signal(ev.subtype)
        if ev.type == 'request':
            return await self._handle_request(ev.subtype)
        return None

    async def _handle_signal(self, subtype: str) -> str:
        if subtype == 'stop':
            for sub in list(self._sub_agents.values()):
                await sub.stop()
            self._stop_event.set()
            return 'stopped'
        return f'unknown signal: {subtype}'

    async def _handle_request(self, subtype: str) -> Any:
        if subtype == 'ping':
            return 'pong'
        if subtype == 'status':
            return {
                'name': self.name,
                'running': self.is_running,
                'state': self.state,
                'has_client': self.client is not None,
                'sub_agent_count': len(self._sub_agents),
            }
        if subtype == 'list_sub_agents':
            return {
                'sub_agents': list(self._sub_agents.keys()),
            }
        return None

    async def _wait_for_background(self, timeout: float = None):
        waits = [
            a._task_completed.wait() for a in self._sub_agents.values()
            if a.config.background and a._task is not None and not a._task.done()
        ]
        if not waits:
            return
        await asyncio.wait(waits, timeout=timeout)

    async def chat(self, message: str) -> str:
        return await self._handle_chat_locked(message)

    def on(self, event: str, handler: Callable):
        self._runtime.subscribe(
            f'lifecycle:{self.kind}:{event}',
            lambda ev: handler(self, **ev.data),
        )
        return self

    def clear(self):
        self._notifications.clear()
        if self.client:
            self.client.clear()

    def _drain_notifications(self):
        context = []
        for n in self._notifications:
            source = n.get('agent_name') or n.get('name') or 'notice'
            content = n.get('content') or n.get('error') or ''
            context.append({'role': 'system', 'content': f'[{source}] {content}'})
        self._notifications.clear()
        return context or None

    async def _notify_parent(self, result: str):
        if not self._parent:
            return
        entry = self._runtime.lookup_entity(self._parent)
        kind = entry[0] if entry else self.kind
        await self._runtime.publish(Event(
            topic=f'entity:{kind}:{self._parent}:notification',
            source=self.id,
            data={
                'content': result,
                'agent_name': self.name,
                'description': self.description,
                'subtype': 'task_complete',
            },
        ))

    @property
    def total_usage(self) -> Usage:
        total = Usage(
            self._usage.prompt_tokens,
            self._usage.completion_tokens,
            self._usage.total_tokens,
        )
        for sub in self._sub_agents.values():
            total += sub.total_usage
        return total

    async def _handle_chat_locked(self, message: str) -> str:
        async with self._lock:
            return await self._handle_chat_inner(message)

    async def _handle_chat_inner(self, message: str) -> str:
        self._task_completed.clear()
        await self._emit('start', {'message': message})
        if not self.client:
            await self._emit('error', {'error': 'No LLM client configured'})
            self._task_completed.set()
            return 'Error: No LLM client configured'
        try:
            result = await self._loop.run(message, context=self._drain_notifications())
            await self._wait_for_background()
            if self._loop.usage:
                self._usage += self._loop.usage
            await self._emit('end', {'content': result})
            await self._emit('tokens', {'usage': self.total_usage})
            if self.config.background:
                await self._notify_parent(result)
            return result
        except Exception as e:
            await self._emit('error', {'error': str(e)})
            raise
        finally:
            self._task_completed.set()

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
                'max_steps': self.config.max_steps,
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
    ) -> 'Agent':
        config = AgentConfig(
            name=state['name'],
            instruction=state.get('instruction', ''),
            provider=state['config']['provider'],
            model=state['config']['model'],
            thinking=state['config'].get('thinking', False),
            http_options=state['config'].get('http_options', {}),
            max_steps=state['config'].get('max_steps', 10),
            tools=tools,
        )
        agent = Agent(config)
        agent.load_state_dict(state)
        return agent


def create_agent(config: AgentConfig) -> 'Agent':
    agent = Agent(config)
    if not config.background:
        agent.start()
    return agent