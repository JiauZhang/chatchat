from __future__ import annotations
from dataclasses import dataclass

from chatchat.agent import Agent, AgentConfig, BaseAgentConfig, create_agent
from chatchat.agent_tools import (
    delegate_task,
    send_message_tool,
    task_stop_tool,
)
from chatchat.exceptions import SubAgentError
from chatchat.runtime import make_id
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
    name='create_agent',
    description='Create a sub-agent for delegated tasks. Use this when a task is independent enough to run separately, or when you need parallel work.',
    parameters={
        'type': 'object',
        'properties': {
            'instruction': {'type': 'string', 'description': 'Task description for the sub-agent'},
        },
        'required': ['instruction'],
    },
)
async def create_agent_tool(ctx: ToolContext, instruction: str) -> str:
    team = ctx.agent
    agent_id = make_id()
    tools = list(team.agent_tools or []) + [send_message_tool]
    cfg = AgentConfig(**_inherit(team.config, name=agent_id, instruction=instruction,
                                 tools=tools, source='user'))
    sub = team.create_sub_agent(cfg)
    result = await delegate_task(team, sub, instruction)
    return f'[Agent "{agent_id}" completed]\n{result}'


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
    result = await delegate_task(team, sub_team, instruction)
    return f'[Team "{team_id}" completed]\n{result}'


class Team(Agent):
    def __init__(self, config: TeamConfig):
        super().__init__(config, kind='team')

    def _build_tools(self):
        mgmt_tools = [
            create_agent_tool,
            create_team_tool,
            send_message_tool,
            task_stop_tool,
        ]
        return list(self.config.leader_tools or []) + mgmt_tools

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