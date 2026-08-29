from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Callable

from chatchat.agents.actor import Actor
from chatchat.agents.loop import AgentLoop
from chatchat.core.event import Event
from chatchat.providers.client import ClientConfig, create_client
from chatchat.providers.protocol import Usage
from chatchat.tools.registry import Tools
from chatchat.tools.skills import Skills


@dataclass
class BaseAgentConfig(ClientConfig):
    id: str | None = None
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
    def __init__(self, config: AgentConfig, kind: str = 'agent', runtime=None):
        self.config = config
        self.description = config.description
        super().__init__(kind, ident=config.id, runtime=runtime)
        if config.id is None:
            config.id = self.id
        self._setup_tools()
        self._setup_skills()
        self._setup_client()
        self._notifications: list[dict] = []
        self._usage = Usage()
        self._loop = AgentLoop(
            self.client, self.tools, config.max_steps, config.thinking, self.id,
            agent=self, allowed_tools=self.allowed_tools, runtime=self._runtime,
        )

    @property
    def provider(self):
        return self.config.provider

    @property
    def model(self):
        return self.config.model

    def _setup_tools(self):
        self.tool_names: set[str] = set(self.config.tools or [])
        resolved = [t for t in (self._runtime.registry.resolve(n) for n in self.tool_names) if t]
        unknown = self.tool_names - {t.name for t in resolved}
        if unknown:
            raise ValueError(f'Agent "{self.id}" references unknown tools: {sorted(unknown)}')
        self.tools = Tools(*resolved) if resolved else None

    @property
    def allowed_tools(self) -> set[str]:
        return self.tool_names

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
            client_config.emit = self._emit_client
            self.client = create_client(client_config)

    async def _emit_client(self, topic: str, data: dict):
        await self._runtime.publish(Event(
            topic=f'lifecycle:{topic}', source=self.id, data=data or {},
        ))

    async def stop(self, timeout: float = 2.0):
        await super().stop(timeout=timeout)
        if self.client:
            await self.client.close()

    async def handle_message(self, ev: Event) -> Any:
        if ev.type == 'text':
            return await self._handle_chat(ev.data)
        if ev.type == 'notification':
            self._notifications.append(ev.data)
            if ev.source in self._pending_reply:
                count, deadline = self._pending_reply[ev.source]
                if count - 1 <= 0:
                    del self._pending_reply[ev.source]
                else:
                    self._pending_reply[ev.source] = (count - 1, deadline)
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
                'id': self.id,
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

    def on(self, event: str, handler: Callable):
        self._runtime.subscribe(
            f'lifecycle:{self.kind}:{event}',
            lambda ev: handler(self, ev.data),
        )
        return self

    def clear(self):
        self._notifications.clear()
        if self.client:
            self.client.clear()

    def _drain_notifications(self):
        context = []
        for n in self._notifications:
            source = n.get('agent_id') or n.get('id') or 'notice'
            content = n.get('content') or n.get('error') or ''
            context.append({'role': 'system', 'content': f'[{source}] {content}'})
        self._notifications.clear()
        return context or None

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

    async def _handle_chat(self, message: str) -> str:
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
            return result
        except Exception as e:
            await self._emit('error', {'error': str(e)})
            raise
        finally:
            self._task_completed.set()

    def state_dict(self) -> dict:
        return {
            'id': self.config.id or self.id,
            'instruction': self.instruction,
            'messages': self.client.messages if self.client else [],
            'config': {
                'provider': self.config.provider,
                'model': self.config.model,
                'thinking': self.config.thinking,
                'http_options': self.config.http_options,
                'max_steps': self.config.max_steps,
                'background': self.config.background,
                'description': self.config.description,
                'skills': self.config.skills,
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
        runtime=None,
    ) -> 'Agent':
        config = AgentConfig(
            id=state.get('id'),
            instruction=state.get('instruction', ''),
            provider=state['config']['provider'],
            model=state['config']['model'],
            thinking=state['config'].get('thinking', False),
            http_options=state['config'].get('http_options', {}),
            max_steps=state['config'].get('max_steps', 10),
            background=state['config'].get('background', False),
            description=state['config'].get('description', ''),
            skills=state['config'].get('skills'),
            tools=tools,
        )
        agent = Agent(config, runtime=runtime)
        agent.load_state_dict(state)
        return agent


def create_agent(config: AgentConfig, runtime=None) -> 'Agent':
    agent = Agent(config, runtime=runtime)
    agent.start()
    return agent
