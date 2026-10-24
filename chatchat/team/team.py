from __future__ import annotations

import asyncio
from pathlib import Path

from chatchat.tool import ToolContext
from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.agent import Agent
from chatchat.team.agents import (
    GENERAL_PURPOSE,
    AgentDefinition,
    AgentRegistry,
)
from chatchat.team.compaction import Compactor
from chatchat.team.courier import Courier
from chatchat.team.host_tasks import HostTasks
from chatchat.team.mailbox import FileMailbox, idle_notification as _idle_msg
from chatchat.team.isolation import Isolation
from chatchat.team.ledger import Ledger
from chatchat.team.model import ModelChoice
from chatchat.team.product import TeamProduct
from chatchat.team.roster import Roster
from chatchat.team.tool_surface import ToolSurface
from chatchat.runtime.context import AgentContext
from chatchat.runtime.filehistory import FileHistory
from chatchat.team.team_store import TeamStore
from chatchat.runtime.skills import SkillRegistry
from chatchat.runtime.thinking import Thinking
from chatchat.team.subagents import SubagentsMixin
from chatchat.tools.registry import ToolRegistry
from chatchat.tools.tool_runner import ToolRunnerMixin
from chatchat.hooks.events import AGENT_WARN, emit
from chatchat.hooks.manager import HookManager

LEAD_NAME = "team-lead"


DEFAULT_COMPACT_RESERVE = 40_000
MAX_COMPACT_FAILURES = 3


def _plural_work(count: int, noun: str, qualifier: str = "") -> str:
    return f"{count} {qualifier}{noun}" + ("" if count == 1 else "s")


class Team(SubagentsMixin, ToolRunnerMixin):
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
        tool_context: ToolContext = None,
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
        multi_agent: bool = True,
        **client_kw,
    ):
        self.name = name
        self.lead_session_id = ""
        self.multi_agent = multi_agent
        self._model_timeout = model_timeout
        self._model_retries = model_retries
        self.model_choice = ModelChoice(
            factory=client_factory,
            client=client,
            model=model,
            thinking=thinking,
            client_kw=client_kw,
        )
        self.tools = ToolSurface(owner=self, injected=tools)
        self.tool_context = tool_context or ToolContext(cwd=Path.cwd())
        self.instruction_files: list[dict] = []
        self.courier = Courier(
            self.name,
            mailbox_root=mailbox_dir,
            tasks_root=tasks_dir,
            team_store=TeamStore(Path(team_store)) if team_store else None,
        )
        self.name = self.courier.name
        self.tasks = self.courier.tasks
        self.file_history = FileHistory(Path(file_history_dir), cwd=self.tool_context.cwd) if file_history_dir else None
        self.tool_context.files = self.file_history
        self.skills = skills or SkillRegistry()
        self.permission_gate = None
        self.agent_memory = agent_memory
        self.rules = rules
        self.ask_user = None
        self.isolation = Isolation()
        self.product: TeamProduct | None = None
        self.host_tasks: HostTasks | None = None
        self.plan_path = None
        self._factory = client_factory
        self.hooks = HookManager(self, enabled=hooks)
        self.roster = Roster(self.name)
        self._counter = 0
        self._session_started = False
        self._session_setup_done = False
        self._session_source = "startup"
        self.context_window = int(context_window or 0)
        self.compactor = Compactor(
            summarize=self._summarize,
            hooks=self.hooks,
            window=self.context_window,
            reserve=compact_reserve,
            on_compacted=self.reset_rules,
        )
        self.sidechain_dir = sidechain_dir
        self.agent_defs = AgentRegistry()
        self.agent_defs.define(
            GENERAL_PURPOSE,
            tools=self.tools.injected,
            default=True,
            description="General-purpose agent that inherits the team tools for routine tasks",
        )
        self.lead = self.create_agent(LEAD_NAME, instruction=lead_instruction, leader=True)
        self.ledger = Ledger(lead=self.lead, members=lambda: self.roster.agents.values())

    def attach(self, product: TeamProduct) -> TeamProduct:
        self.product = product
        return product

    def register_agent_definition(self, defn) -> AgentDefinition:
        return self.agent_defs.register(defn)

    def remove_agent_definition(self, agent_type: str) -> bool:
        return self.agent_defs.remove(agent_type)

    def define_agent(
        self,
        agent_type: str,
        *,
        system_prompt: str = "",
        tools: list = None,
        model: str | None = None,
        addenda: str = "",
        default: bool = False,
    ) -> AgentDefinition:
        return self.agent_defs.define(
            agent_type, system_prompt=system_prompt, tools=tools, model=model, addenda=addenda, default=default
        )

    async def _summarize(self, messages: list[dict]) -> str:
        client = self._client_for("Summarize the conversation so far.", standing=False)
        return await client.respond(messages)

    def _client_for(self, instruction: str, thinking: Thinking | None = None, model: str | None = None, standing: bool = True):
        return self.model_choice.client_for(instruction, thinking=thinking, model=model, standing=standing)

    def agent_id(self, name: str) -> str:
        return self.roster.id_of(name)

    def get(self, agent_id: str) -> Agent | None:
        return self.roster.get(agent_id)

    def get_by_name(self, name: str) -> Agent | None:
        return self.roster.get_by_name(name)

    def create_agent(self, name: str, instruction: str = "", model=None, leader: bool = False, depth: int = 0) -> Agent:
        agent_id = self.agent_id(name)
        abort = AbortSignal()
        ctx = AgentContext(agent_id=agent_id, agent_name=name, team_name=self.name, abort=abort, leader=leader)
        inbox = None
        if self.courier.mailbox_dir is not None:
            inbox = FileMailbox(self.courier.mailbox_path(name))
        agent = Agent(
            agent_id,
            name,
            self,
            self._client_for(instruction, model=model),
            ctx,
            instruction=instruction,
            inbox=inbox,
            depth=depth,
            model_timeout=self._model_timeout,
            model_retries=self._model_retries,
        )
        self.roster.add(agent)
        agent.start()
        if self.courier.team_store is not None and self.courier.team_context is not None:
            self.courier.team_store.note_member(
                self.name,
                {
                    "agent_id": agent_id,
                    "name": name,
                    "model": str(getattr(agent.client, "model", "") or ""),
                    "prompt": instruction,
                },
            )
        return agent

    def add(self, name: str, instruction: str = "") -> Agent:
        return self.create_agent(name, instruction=instruction)

    def transcript(self) -> list[dict]:
        return list(self.lead.messages)

    def restore(self, messages: list[dict]):
        self.lead.messages = [m for m in messages if isinstance(m, dict)]
        if self.lead.messages:
            self._session_source = "resume"

    async def end_session(self, reason: str):
        await self.hooks.execute_session_end_hooks(reason)

    def begin_new_session(self, source: str = "clear"):
        self._session_source = source
        self._session_started = False

    async def _open_session(self):
        aggs = []
        if not self._session_setup_done:
            self._session_setup_done = True
            aggs.append(await self.hooks.execute_setup_hooks())
        aggs.append(await self.hooks.execute_session_start_hooks(self._session_source))
        for agg in aggs:
            if agg.additional_context:
                self.lead.messages.append({"role": "user", "content": agg.additional_context})

    def set_instruction_files(self, files: list[dict]):
        self.instruction_files = list(files or [])

    def set_lead_instruction(self, instruction: str):
        lead = self.get_by_name(LEAD_NAME)
        if lead is None:
            return
        lead.instruction = instruction
        lead.client = self._client_for(instruction)

    def set_thinking(self, thinking: Thinking):
        self.model_choice.set_thinking(thinking)
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None:
            lead.client = self._client_for(lead.instruction)

    def set_model(self, model: str):
        self.model_choice.set_model(model)
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None:
            lead.client = self._client_for(lead.instruction)

    @property
    def provider(self):
        return self.model_choice.provider

    @property
    def model(self):
        return self.model_choice.model

    @property
    def thinking(self):
        return self.model_choice.thinking

    @property
    def tool_registry(self) -> ToolRegistry:
        return self.tools.registry()

    def tool_schemas(self, context) -> list[dict]:
        return self.tools.schemas(context)

    @property
    def provided_tools(self):
        return self.tools.provided()

    async def query(self, prompt: str, timeout: float | None = None) -> str:
        if not self._session_started:
            self._session_started = True
            await self._open_session()
        if self.file_history is not None:
            self.file_history.snapshot(len(self.lead.messages))
        self.lead.submit(prompt)
        start = len(self.lead.messages)
        if timeout is None:
            await self.lead.wait_idle()
        else:
            try:
                await asyncio.wait_for(self.lead.wait_idle(), timeout)
            except asyncio.TimeoutError:
                pass
        return self.lead.last_assistant(start=start)

    def use_file_history(self, directory) -> None:
        """Point the snapshot store at a directory, dropping what was read
        from the previous one."""
        self.file_history = FileHistory(Path(directory), cwd=self.tool_context.cwd)
        self.tool_context.files = self.file_history

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

    def set_cwd(self, path):
        cwd = Path(path)
        self.tool_context.cwd = cwd
        self.hooks.set_cwd(cwd)
        if self.file_history is not None:
            self.file_history.cwd = cwd
        if self.product is not None:
            self.product.cwd_changed(cwd)

    def set_plan_mode(self, mode: str) -> None:
        if self.product is not None:
            self.product.plan_mode_changed(mode)
        else:
            self.hooks.permission_mode = mode

    def turns(self) -> list[tuple[int, str]]:
        if self.file_history is None:
            return []
        marks = {snap.mark for snap in self.file_history.snapshots}
        return [
            (index, str(message.get("content") or ""))
            for index, message in enumerate(self.lead.messages)
            if index in marks and message.get("role") == "user"
        ]

    def rewind(self, mark: int, *, code: bool = True, conversation: bool = True) -> dict:
        files = self.file_history.rewind(mark) if code and self.file_history is not None else []
        removed = 0
        if conversation:
            kept = self.lead.messages[: int(mark)]
            removed = len(self.lead.messages) - len(kept)
            self.lead.messages = list(kept)
        return {"files": files, "messages": removed}

    def send_control(self, recipient_name: str, payload: str):
        recipient = self.get_by_name(recipient_name)
        if recipient is not None:
            recipient.inbox.write(self.lead.agent_id, payload)

    async def notify_idle(
        self,
        agent: Agent,
        *,
        reason: str = "available",
        summary: str = "",
        completed_task_id: str = "",
        completed_status: str = "resolved",
        failure_reason: str | None = None,
    ):
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None and agent.agent_id != lead.agent_id:
            lead.inbox.write(
                agent.agent_id,
                _idle_msg(
                    agent.name,
                    idle_reason=reason,
                    summary=summary,
                    completed_task_id=completed_task_id,
                    completed_status=completed_status,
                    failure_reason=failure_reason or "",
                ),
            )
        if reason == "failed" and failure_reason:
            emit(AGENT_WARN, agent=agent.name, text=failure_reason)

    def request_shutdown(self, agent_id: str):
        agent = self.roster.get(agent_id)
        if agent is not None:
            asyncio.get_running_loop().create_task(agent.stop())
