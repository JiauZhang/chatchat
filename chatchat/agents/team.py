from __future__ import annotations
from dataclasses import dataclass

from chatchat.agents.agent import Agent, AgentConfig, BaseAgentConfig, create_agent
from chatchat.core.exceptions import SubAgentError
from chatchat.tools.registry import Tools


@dataclass
class TeamConfig(BaseAgentConfig):
    leader_tools: list | None = None
    agent_tools: list | None = None


def create_team(config: TeamConfig, runtime=None) -> Team:
    team = Team(config, runtime=runtime)
    team.start()
    return team


class Team(Agent):
    def __init__(self, config: TeamConfig, runtime=None):
        super().__init__(config, kind='team', runtime=runtime)

    def _setup_tools(self):
        self.tool_names: set[str] = set(self._build_tools())
        resolved = [t for t in (self._runtime.registry.resolve(n) for n in self.tool_names) if t]
        unknown = self.tool_names - {t.name for t in resolved}
        if unknown:
            raise ValueError(f'Team "{self.id}" references unknown tools: {sorted(unknown)}')
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
        agent = create_agent(config, runtime=self._runtime)
        agent._depth = self._depth + 1
        self._sub_agents[agent.id] = agent
        return agent

    def create_sub_team(self, config: TeamConfig) -> 'Team':
        if self._depth + 1 > self.config.max_depth:
            raise SubAgentError(
                f'Recursion depth limit {self.config.max_depth} exceeded'
            )
        team = create_team(config, runtime=self._runtime)
        team._depth = self._depth + 1
        self._sub_agents[team.id] = team
        return team
