from __future__ import annotations
from dataclasses import dataclass, replace

from chatchat.agent import Agent, AgentConfig
from chatchat.agent_tools import (
    create_agent_tool,
    delegate_task,
    send_message_tool,
    task_stop_tool,
)
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