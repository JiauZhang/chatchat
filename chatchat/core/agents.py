from __future__ import annotations

from dataclasses import dataclass, field

GENERAL_PURPOSE = 'general-purpose'


@dataclass
class AgentDefinition:
    agent_type: str
    system_prompt: str = ''
    tools: list = field(default_factory=list)
    model: str | None = None
    permission_mode: str | None = None
    default: bool = False
    addenda: str = ''
    description: str = ''

    def full_prompt(self) -> str:
        parts = [p.strip() for p in (self.system_prompt, self.addenda) if p.strip()]
        return '\n'.join(parts)


def general_purpose(system_prompt: str = '', tools: list = None) -> AgentDefinition:
    return AgentDefinition(GENERAL_PURPOSE, system_prompt=system_prompt,
                           tools=list(tools or []), default=True)


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
               model: str | None = None, addenda: str = '', default: bool = False,
               description: str = '') -> AgentDefinition:
        return self.register(AgentDefinition(
            agent_type, system_prompt=system_prompt, tools=list(tools or []),
            model=model, addenda=addenda, default=default,
            description=description))

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

    def find(self, agent_type: str) -> AgentDefinition | None:
        return self._defs.get(agent_type)

    def remove(self, agent_type: str) -> bool:
        if self._defs.pop(agent_type, None) is None:
            return False
        if self._default is not None and self._default.agent_type == agent_type:
            self._default = next(iter(self._defs.values()), None)
        return True

    def types(self) -> list[str]:
        return sorted(self._defs)

    def describe(self) -> list[tuple[str, str]]:
        return [(d.agent_type, d.description) for d in self._defs.values()
                if d.description]
