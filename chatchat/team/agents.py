from __future__ import annotations

from dataclasses import dataclass, field

GENERAL_PURPOSE = "general-purpose"
CC_ALIASES = ("sonnet", "opus", "haiku")


def agent_model_problem(value) -> str:
    """The load-time warning for a model value pyclaw can never resolve: a
    claude-code alias. The file's author should be told why it will not run."""
    text = str(value or "").strip()
    if text.lower() in CC_ALIASES:
        return (
            f"model '{text}' is a claude-code alias; pyclaw models are the "
            "provider's model names (the config's \"model\" field) or inherit"
        )
    return ""


def resolve_agent_model(value, provider) -> tuple[str | None, str]:
    """(model, problem) at spawn time, with the team's provider known. None
    means the parent model. A provider/model pair must name this team's
    provider; a bare name is that provider's model, exactly like the config's
    model field; claude-code aliases cannot resolve here."""
    text = str(value or "").strip()
    if not text or text == "inherit":
        return None, ""
    if "/" in text:
        front, _, model = text.partition("/")
        if front.strip().lower() == str(provider).strip().lower() and model.strip():
            return model.strip(), ""
        return None, (f"model '{text}' is not available to provider '{provider}'; use one of its model names or inherit")
    if text.lower() in CC_ALIASES:
        return None, f"model '{text}' is a claude-code alias; use the provider's model name or inherit"
    return text, ""


@dataclass
class AgentDefinition:
    agent_type: str
    system_prompt: str = ""
    tools: list = field(default_factory=list)
    model: str | None = None
    permission_mode: str | None = None
    default: bool = False
    addenda: str = ""
    description: str = ""
    memory: str | None = None

    def full_prompt(self) -> str:
        parts = [p.strip() for p in (self.system_prompt, self.addenda) if p.strip()]
        return "\n".join(parts)


def general_purpose(system_prompt: str = "", tools: list = None) -> AgentDefinition:
    return AgentDefinition(GENERAL_PURPOSE, system_prompt=system_prompt, tools=list(tools or []), default=True)


class AgentRegistry:
    def __init__(self):
        self._defs: dict[str, AgentDefinition] = {}
        self._default: AgentDefinition | None = None

    def register(self, defn: AgentDefinition) -> AgentDefinition:
        self._defs[defn.agent_type] = defn
        if defn.default or self._default is None:
            self._default = defn
        return defn

    def define(
        self,
        agent_type: str,
        *,
        system_prompt: str = "",
        tools: list = None,
        model: str | None = None,
        addenda: str = "",
        default: bool = False,
        description: str = "",
        memory: str | None = None,
    ) -> AgentDefinition:
        return self.register(
            AgentDefinition(
                agent_type,
                system_prompt=system_prompt,
                tools=list(tools or []),
                model=model,
                addenda=addenda,
                default=default,
                description=description,
                memory=memory,
            )
        )

    def get(self, agent_type: str | None) -> AgentDefinition:
        if agent_type:
            defn = self._defs.get(agent_type)
            if defn is None:
                raise KeyError(f'unknown agent type "{agent_type}"; registered: {sorted(self._defs)}')
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
        return [(d.agent_type, d.description) for d in self._defs.values() if d.description]
