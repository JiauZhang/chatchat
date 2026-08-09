from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from chatchat.agent import BaseAgent, AgentConfig, create_agent
from chatchat.message import ID, Message


@dataclass
class TeamConfig:
    name: str
    leader: AgentConfig


def create_team(config: TeamConfig, scheduler) -> Team:
    team = Team(config, scheduler)
    scheduler.register(team)
    team.start()
    return team


class Team(BaseAgent):
    def __init__(self, config: TeamConfig, scheduler):
        id = ID(uid=config.name, kind='team', name=config.name)
        super().__init__(id, scheduler)
        self._leader = create_agent(config.leader, scheduler)

    @property
    def name(self) -> str:
        return self.id.name

    @property
    def leader(self):
        return self._leader

    def start(self):
        super().start()
        self._leader.start()

    def stop(self, timeout: float = 2.0):
        self._leader.stop(timeout=timeout)
        super().stop(timeout=timeout)

    def handle_message(self, msg: Message) -> Any:
        if msg.type in ('text', 'request', 'signal'):
            return self._leader.handle_message(msg)
        return None