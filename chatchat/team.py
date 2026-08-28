from __future__ import annotations
from dataclasses import dataclass

from chatchat.agent import Agent, AgentConfig, BaseAgentConfig, create_agent
from chatchat.exceptions import SubAgentError
from chatchat.runtime import ensure_builtin_tools
from chatchat.tool import Tools, get_registry
from chatchat.runtime import Event, make_id
from chatchat.tool import tool, ToolContext


def _inherit(config, **overrides):
    data = {f: getattr(config, f) for f in BaseAgentConfig.__dataclass_fields__}
    data.update(overrides)
    return data


@dataclass
class TeamConfig(BaseAgentConfig):
    leader_tools: list | None = None
    agent_tools: list | None = None


def create_team(config: TeamConfig) -> Team:
    team = Team(config)
    team.start()
    return team


@tool(
    name='create_team',
    description='Create a sub-team for delegated tasks. Returns the team name for communication.',
    parameters={
        'type': 'object',
        'properties': {
            'instruction': {'type': 'string', 'description': 'Task description for the sub-team'},
        },
        'required': ['instruction'],
    },
)
async def create_team_tool(ctx: ToolContext, instruction: str) -> str:
    team = ctx.agent
    team_id = make_id()
    cfg = TeamConfig(**_inherit(team.config, name=team_id, instruction=instruction,
                                leader_tools=None, agent_tools=team.agent_tools, source='user'))
    sub_team = team.create_sub_team(cfg)
    # Fire-and-forget: the sub-team reports back via notification.
    await team._runtime.publish(Event(
        topic=f'entity:team:{sub_team.id}:text',
        source=team.id, data=instruction,
    ))
    return f'[Team "{team_id}" spawned; it will report back when done]'


class Team(Agent):
    def __init__(self, config: TeamConfig):
        super().__init__(config, kind='team')

    def _setup_tools(self):
        ensure_builtin_tools()
        self.tool_names: set[str] = set(self._build_tools())
        resolved = [t for t in (get_registry().resolve(n) for n in self.tool_names) if t]
        unknown = self.tool_names - {t.name for t in resolved}
        if unknown:
            raise ValueError(f'Team "{self.name}" references unknown tools: {sorted(unknown)}')
        self.tools = Tools(*resolved) if resolved else None

    def _build_tools(self):
        mgmt_tool_names = ['create_agent', 'create_team', 'send_message', 'task_stop']
        return list(self.config.leader_tools or []) + mgmt_tool_names

    @property
    def agent_tools(self):
        return self.config.agent_tools

    def create_sub_agent(self, config: AgentConfig) -> 'Agent':
        if self._depth + 1 > self.config.max_depth:
            raise SubAgentError(
                f'Recursion depth limit {self.config.max_depth} exceeded'
            )
        agent = create_agent(config)
        agent._parent = self.id
        agent._depth = self._depth + 1
        self._sub_agents[config.name] = agent
        return agent

    def create_sub_team(self, config: TeamConfig) -> 'Team':
        if self._depth + 1 > self.config.max_depth:
            raise SubAgentError(
                f'Recursion depth limit {self.config.max_depth} exceeded'
            )
        team = create_team(config)
        team._parent = self.id
        team._depth = self._depth + 1
        self._sub_agents[config.name] = team
        return team