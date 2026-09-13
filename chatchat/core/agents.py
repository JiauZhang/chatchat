from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field

GENERAL_PURPOSE = 'general-purpose'


@dataclass
class AgentDefinition:
    agent_type: str
    system_prompt: str = ''
    tools: list = field(default_factory=list)
    model: str | None = None
    default: bool = False
    addenda: str = ''

    def tool_schemas(self) -> list[dict]:
        return [{'name': t.name,
                 'description': t.description,
                 'input_schema': t.parameters or {}}
                for t in self.tools]

    async def execute_tool(self, name: str, input: dict, agent=None,
                           tool_use_id: str = '') -> str:
        tool = next((t for t in self.tools if t.name == name), None)
        if tool is None:
            return f'Error: unknown tool "{name}"'
        try:
            out = tool(**input)
            if inspect.iscoroutine(out):
                out = await out
            return out if isinstance(out, str) else str(out)
        except Exception as e:
            return f'Error calling tool "{name}": {type(e).__name__}: {e}'

    def full_prompt(self) -> str:
        parts = [p.strip() for p in (self.system_prompt, self.addenda) if p.strip()]
        return '\n'.join(parts)


def general_purpose(system_prompt: str = '', tools: list = None) -> AgentDefinition:
    return AgentDefinition(GENERAL_PURPOSE, system_prompt=system_prompt,
                           tools=list(tools or []), default=True)


async def run_agent(prompt: str, *, provider: str = None, model: str = None,
                    system_prompt: str = '', tools: list = None,
                    addenda: str = '', thinking: bool = True,
                    client=None, agent_type: str | None = None,
                    fork_msgs: list | None = None, max_steps: int = 20,
                    model_timeout: float = 120.0) -> str:
    from chatchat.client import Client
    from chatchat.core.abort import AbortSignal
    from chatchat.core.agent import Agent
    from chatchat.core.context import AgentContext
    from chatchat.core.task import rand_name

    defn = AgentDefinition(agent_type or GENERAL_PURPOSE,
                           system_prompt=system_prompt, tools=list(tools or []),
                           model=model, addenda=addenda)
    sys_prompt = defn.full_prompt()
    if client is None:
        client = Client(provider, model=model or defn.model,
                        instruction=sys_prompt, thinking=thinking)
    name = rand_name('agent')
    ctx = AgentContext(agent_id=name, agent_name=name, team_name='',
                       abort=AbortSignal(), leader=False)
    agent = Agent(name, name, None, client, ctx, instruction=sys_prompt,
                  max_steps=max_steps, internal=True, tool_exec=defn,
                  model_timeout=model_timeout)
    if fork_msgs:
        agent.messages = list(fork_msgs)
    return await agent.chat(prompt)


class AgentRegistry:

    def __init__(self):
        self._defs: dict[str, AgentDefinition] = {}
        self._default: AgentDefinition | None = None

    def register(self, defn: AgentDefinition) -> AgentDefinition:
        self._defs[defn.agent_type] = defn
        if defn.default or self._default is None:
            self._default = defn
        return defn

    def define(self, agent_type: str, *, system_prompt: str = '', tools: list = None,
               model: str | None = None, addenda: str = '', default: bool = False) \
            -> AgentDefinition:
        return self.register(AgentDefinition(
            agent_type, system_prompt=system_prompt, tools=list(tools or []),
            model=model, addenda=addenda, default=default))

    def get(self, agent_type: str | None) -> AgentDefinition:
        if agent_type:
            defn = self._defs.get(agent_type)
            if defn is None:
                raise KeyError(f'unknown agent type "{agent_type}"; '
                               f'registered: {sorted(self._defs)}')
            return defn
        if self._default is None:
            self.register(general_purpose())
        return self._default

    def types(self) -> list[str]:
        return sorted(self._defs)
