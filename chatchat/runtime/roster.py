from __future__ import annotations

import asyncio


class Roster:
    """The agents of a team, and how they are related.

    A team is its agents: who is in it, who spawned whom, and which of them
    are still running. The roster holds that and the operations on it, so the
    team does not carry four dictionaries and the rules that go with them.
    """

    def __init__(self, team_name: str):
        self.team_name = team_name
        self.agents: dict = {}
        self.background: dict[str, asyncio.Task] = {}
        self.children: dict[str, set[str]] = {}
        self.parents: dict[str, str] = {}

    def rename(self, name: str) -> None:
        self.team_name = name

    def id_of(self, name: str) -> str:
        return f"{name}@{self.team_name}"

    def get(self, agent_id: str):
        return self.agents.get(agent_id)

    def get_by_name(self, name: str):
        return self.agents.get(self.id_of(name))

    def add(self, agent) -> None:
        self.agents[agent.agent_id] = agent

    def link(self, parent_id: str, child_id: str) -> None:
        self.parents[child_id] = parent_id
        self.children.setdefault(parent_id, set()).add(child_id)

    def unlink(self, child_id: str) -> None:
        parent = self.parents.pop(child_id, None)
        if parent and child_id in self.children.get(parent, set()):
            self.children[parent].discard(child_id)

    def track_background(self, agent_id: str, task) -> None:
        self.background[agent_id] = task
        task.add_done_callback(lambda done: self.background.pop(agent_id, None))

    def running_teammates(self, lead) -> list:
        return [agent for agent in self.agents.values() if agent is not lead and not agent._internal and agent.is_running]
