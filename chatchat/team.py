from __future__ import annotations
from dataclasses import dataclass, replace

from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.agent_tools import (
    delegate_task,
    send_message_tool,
    task_stop_tool,
)
from chatchat.exceptions import SubAgentError
from chatchat.runtime import make_id
from chatchat.tool import tool, ToolContext


@dataclass
class TeamConfig(AgentConfig):
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
    agent_tools = getattr(team.config, 'agent_tools', None)
    cfg = replace(team.config, name=agent_id, instruction=instruction,
                  tools=agent_tools, source='user')
    sub = team.create_sub_agent(cfg)
    sub.add_tool(send_message_tool)
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
    cfg = replace(team.config, name=team_id, instruction=instruction,
                  agent_tools=getattr(team.config, 'agent_tools', None), source='user')
    sub_team = team.create_sub_team(cfg)
    result = await delegate_task(team, sub_team, instruction)
    return f'[Team "{team_id}" completed]\n{result}'


class Team(Agent):
    def __init__(self, config: TeamConfig):
        mgmt_tools = [
            create_agent_tool,
            create_team_tool,
            send_message_tool,
            task_stop_tool,
        ]
        leader_tools = list(config.leader_tools or []) + mgmt_tools
        config = replace(config, tools=list(config.tools or []) + leader_tools)
        super().__init__(config, kind='team')

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

    def create_sub_team(self, config) -> 'Team':
        if self._depth + 1 > self.config.max_depth:
            raise SubAgentError(
                f'Recursion depth limit {self.config.max_depth} exceeded'
            )
        team = create_team(config)
        team._parent = self.id
        team._depth = self._depth + 1
        self._sub_agents[config.name] = team
        return team