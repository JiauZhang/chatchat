from __future__ import annotations

from pathlib import Path

from chatchat.runtime.agent import Agent
from chatchat.runtime.mailbox import FileMailbox
from chatchat.runtime.runtime import DEFAULT_COMPACT_RESERVE, Runtime
from chatchat.runtime.thinking import Thinking
from chatchat.team.courier import Courier
from chatchat.team.team_store import TeamStore


class Team(Runtime):
    """The runtime plus named collaboration: a shared mailbox, a team store
    and a task list that moves with the team name. Execution itself belongs
    to Runtime; this class only adds what several agents share."""

    multi_agent = True

    def __init__(
        self,
        name: str,
        client=None,
        hooks: bool = True,
        client_factory=None,
        lead_instruction: str = "",
        model_timeout: float = 120.0,
        model_retries: int = 2,
        model: str = None,
        thinking: Thinking | None = None,
        tools: list = None,
        tool_context=None,
        context_window: int = 0,
        compact_reserve: int = DEFAULT_COMPACT_RESERVE,
        mailbox_dir=None,
        sidechain_dir=None,
        tasks_dir=None,
        file_history_dir=None,
        skills=None,
        team_store=None,
        agent_memory=None,
        rules=None,
        services=None,
        **client_kw,
    ):
        self.courier = Courier(
            name,
            mailbox_root=mailbox_dir,
            tasks_root=tasks_dir,
            team_store=TeamStore(Path(team_store)) if team_store else None,
        )
        super().__init__(
            self.courier.name,
            client=client,
            hooks=hooks,
            client_factory=client_factory,
            lead_instruction=lead_instruction,
            model_timeout=model_timeout,
            model_retries=model_retries,
            model=model,
            thinking=thinking,
            tools=tools,
            tool_context=tool_context,
            context_window=context_window,
            compact_reserve=compact_reserve,
            sidechain_dir=sidechain_dir,
            file_history_dir=file_history_dir,
            skills=skills,
            agent_memory=agent_memory,
            rules=rules,
            services=services,
            **client_kw,
        )
        self.tasks = self.courier.tasks

    def _inbox_for(self, name: str):
        if self.courier.mailbox_dir is None:
            return None
        return FileMailbox(self.courier.mailbox_path(name))

    def create_agent(self, name: str, instruction: str = "", model=None, leader: bool = False, depth: int = 0) -> Agent:
        agent = super().create_agent(name, instruction=instruction, model=model, leader=leader, depth=depth)
        if self.courier.team_store is not None and self.courier.team_context is not None:
            self.courier.team_store.note_member(
                self.name,
                {
                    "agent_id": agent.agent_id,
                    "name": name,
                    "model": str(getattr(agent.client, "model", "") or ""),
                    "prompt": instruction,
                },
            )
        return agent

    @property
    def team_context(self):
        return self.courier.team_context

    def mailbox_path(self, member: str) -> Path:
        return self.courier.mailbox_path(member)

    def teammates(self) -> list:
        return self.roster.running_teammates(self.lead)

    def join_team(self, name: str, description: str = ""):
        context = self.courier.join(
            name,
            description,
            leader_id=self.lead.agent_id,
            session_id=self.lead_session_id,
        )
        self.name = self.courier.name
        self.roster.rename(self.name)
        self.tasks = self.courier.tasks
        return context

    def leave_team(self):
        self.courier.leave([agent.name for agent in self.teammates()])
