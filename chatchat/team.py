from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from chatchat.agent import AgentConfig, BaseAgentConfig, BaseAgent, create_agent
from chatchat.agent_tools import create_agent_tool, send_message_tool, task_stop_tool
from chatchat.message import Message
from chatchat.runtime import get_runtime


@dataclass
class TeamConfig(BaseAgentConfig):
    leader_tools: list | None = None
    agent_tools: list | None = None


def create_team(config: TeamConfig) -> Team:
    team = Team(config)
    runtime = get_runtime()
    runtime.register(team)
    team.start()
    return team


class Team(BaseAgent):
    def __init__(self, config: TeamConfig):
        self.config = config
        self.kind = 'team'
        super().__init__(config.name)

        leader_tools = list(config.leader_tools or []) + [
            create_agent_tool(self, agent_tools=config.agent_tools),
            send_message_tool(self),
            task_stop_tool(self),
        ]
        leader_config = AgentConfig(
            name=config.name, description=config.description,
            provider=config.provider, model=config.model,
            instruction=config.instruction,
            thinking=config.thinking, skills=config.skills,
            http_options=config.http_options, max_turns=config.max_turns,
            source=config.source, background=config.background,
            tools=leader_tools,
        )
        self._leader = create_agent(leader_config)

    @property
    def name(self) -> str:
        return self.id

    @property
    def leader(self):
        return self._leader

    def start(self):
        super().start()

    def stop(self, timeout: float = 2.0):
        self._leader.stop(timeout=timeout)
        super().stop(timeout=timeout)

    def handle_message(self, msg: Message) -> Any:
        if msg.type in ('text', 'request', 'signal'):
            return self._leader.handle_message(msg)
        return None