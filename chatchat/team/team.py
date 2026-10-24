from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from chatchat.client import Client
from chatchat.tool import ToolContext
from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.agent import Agent
from chatchat.team.agents import (
    GENERAL_PURPOSE,
    AgentDefinition,
    AgentRegistry,
)
from chatchat.team.mailbox import FileMailbox
from chatchat.team.compaction import Compactor
from chatchat.team.product import TeamProduct
from chatchat.runtime.metrics import Metrics
from chatchat.runtime.context import AgentContext
from chatchat.runtime.filehistory import FileHistory
from chatchat.team.mailbox import idle_notification as _idle_msg
from chatchat.tasks.tasks import TaskList
from chatchat.team.team_store import TeamStore
from chatchat.runtime.skills import SkillRegistry
from chatchat.runtime.thinking import Thinking
from chatchat.team.standing import with_standing
from chatchat.runtime.tokens import measured
from chatchat.team.subagents import SubagentsMixin
from chatchat.tools.tool_runner import ToolRunnerMixin
from chatchat.tools.builtin import builtin_tools
from chatchat.tools.registry import ToolRegistry
from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL, retries, schema_problem
from chatchat.hooks.events import AGENT_WARN, emit
from chatchat.hooks.manager import HookManager

LEAD_NAME = "team-lead"


DEFAULT_COMPACT_RESERVE = 40_000
MAX_COMPACT_FAILURES = 3


def _plural_work(count: int, noun: str, qualifier: str = "") -> str:
    return f"{count} {qualifier}{noun}" + ("" if count == 1 else "s")


def token_count(messages: list[dict]) -> int:
    for message in reversed(messages):
        usage = message.get("usage")
        if isinstance(usage, dict):
            return measured(usage)
    return 0


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
        self._client = client
        self._model_timeout = model_timeout
        self._model_retries = model_retries
        self._model = model
        self._thinking = thinking or Thinking()
        self._client_kw = client_kw
        self._injected_tools = list(tools or [])
        self.tool_context = tool_context or ToolContext(cwd=Path.cwd())
        self.instruction_files: list[dict] = []
        self._mailbox_root = Path(mailbox_dir) if mailbox_dir else None
        self._tasks_root = Path(tasks_dir) if tasks_dir else None
        self.team_store = TeamStore(Path(team_store)) if team_store else None
        self.team_context: dict | None = None
        self._mailbox_dir = self._team_mailbox_dir()
        self.tasks = TaskList(self._tasks_root / self.name) if self._tasks_root else None
        self.file_history = FileHistory(Path(file_history_dir), cwd=self.tool_context.cwd) if file_history_dir else None
        self.tool_context.files = self.file_history
        self.skills = skills or SkillRegistry()
        self.permission_gate = None
        self.agent_memory = agent_memory
        self.rules = rules
        self.ask_user = None
        self.isolation_start = None
        self.isolation_end = None
        self.output_schema: dict | None = None
        self.structured_output: dict | None = None
        self._output_attempts = 0
        self._output_hook = None
        self.product: TeamProduct | None = None
        self._agent_isolation: dict[str, str] = {}
        self.plan_path = None
        self._factory = client_factory
        self.hooks = HookManager(self, enabled=hooks)
        self.agents: dict[str, Agent] = {}
        self.background: dict[str, asyncio.Task] = {}
        self.children: dict[str, set[str]] = {}
        self.parents: dict[str, str] = {}
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
            tools=list(self._injected_tools),
            default=True,
            description="General-purpose agent that inherits the team tools for routine tasks",
        )
        self.lead = self.create_agent(LEAD_NAME, instruction=lead_instruction, leader=True)

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
        instruction = with_standing(instruction) if standing else instruction
        if self._factory is not None:
            return self._factory(instruction, model)
        if self._client is not None:
            return self._client
        return Client(
            model=model or self._model,
            instruction=instruction,
            thinking=self._thinking if thinking is None else thinking,
            **self._client_kw,
        )

    def agent_id(self, name: str) -> str:
        return f"{name}@{self.name}"

    def get(self, agent_id: str) -> Agent | None:
        return self.agents.get(agent_id)

    def get_by_name(self, name: str) -> Agent | None:
        return self.agents.get(self.agent_id(name))

    def create_agent(self, name: str, instruction: str = "", model=None, leader: bool = False, depth: int = 0) -> Agent:
        agent_id = self.agent_id(name)
        abort = AbortSignal()
        ctx = AgentContext(agent_id=agent_id, agent_name=name, team_name=self.name, abort=abort, leader=leader)
        inbox = None
        if self._mailbox_dir is not None:
            inbox = FileMailbox(self.mailbox_path(name))
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
        self.agents[agent_id] = agent
        agent.start()
        if self.team_store is not None and self.team_context is not None:
            self.team_store.note_member(
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

    def usage(self):
        total = type(self.lead.total_usage)()
        for agent in self.agents.values():
            total.add(agent.total_usage)
        return total

    def last_usage(self):
        for message in reversed(self.transcript()):
            usage = message.get("usage")
            if isinstance(usage, dict):
                return type(self.lead.total_usage).from_dict(usage)
        return None

    def restore_totals(self, usage: dict, metrics: dict):
        """Carry the numbers of a conversation that is being continued into the
        agent that will keep it, so the counts a person reads go on growing
        instead of starting over. Both per-turn fields are set: the first turn
        after a resume must report its own work, not the whole history."""
        lead = self.lead
        lead.total_usage = type(lead.total_usage).from_dict(usage)
        known = Metrics().as_dict()
        seeded = Metrics(**{name: int(metrics.get(name) or 0) for name in known})
        lead.metrics = seeded
        lead.last_metrics = seeded
        lead.total_metrics = seeded

    def reset_usage(self):
        for agent in self.agents.values():
            agent.total_usage = type(self.lead.total_usage)()
            agent.metrics = Metrics()
            agent.last_metrics = Metrics()
            agent.total_metrics = Metrics()

    def set_instruction_files(self, files: list[dict]):
        self.instruction_files = list(files or [])

    def set_lead_instruction(self, instruction: str):
        lead = self.get_by_name(LEAD_NAME)
        if lead is None:
            return
        lead.instruction = instruction
        lead.client = self._client_for(instruction)

    def set_thinking(self, thinking: Thinking):
        self._thinking = thinking
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None:
            lead.client = self._client_for(lead.instruction)

    def set_model(self, model: str):
        self._model = model
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None:
            lead.client = self._client_for(lead.instruction)

    @property
    def provider(self):
        return str(self._model or "").partition("/")[0]

    @property
    def model(self):
        return self._model

    @property
    def thinking(self):
        return self._thinking

    @property
    def tool_registry(self) -> ToolRegistry:
        return ToolRegistry(builtin_tools(self), self._injected_tools)

    def tool_schemas(self, context) -> list[dict]:
        return self.tool_registry.schemas(context)

    @property
    def provided_tools(self):
        return list(self._injected_tools)

    @property
    def context_tokens(self) -> int:
        return token_count(self.transcript())

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

    def _team_mailbox_dir(self) -> Path | None:
        if self._mailbox_root is None:
            return None
        return self._mailbox_root / self.name / "inboxes"

    def mailbox_path(self, member: str) -> Path:
        return self._mailbox_dir / f"{member}.json"

    def teammates(self) -> list:
        return [agent for agent in self.agents.values() if agent is not self.lead and not agent._internal and agent.is_running]

    def join_team(self, name: str, description: str = ""):
        if self.team_context is not None:
            raise ValueError(f"already in the team {self.name}")
        name = str(name or "").strip()
        if not name:
            raise ValueError("a team needs a name")
        if self.team_store is not None:
            name = self.team_store.unique_name(name)
            self.team_store.create(name, description, leader=self.lead.agent_id, session_id=self.lead_session_id)
        self.name = name
        self._mailbox_dir = self._team_mailbox_dir()
        self.tasks = TaskList(self._tasks_root / name) if self._tasks_root is not None else None
        self.team_context = {"name": name, "description": description}
        return self.team_context

    def leave_team(self):
        if self.team_context is None:
            return
        live = [agent.name for agent in self.teammates()]
        if live:
            raise ValueError("the team still has teammates: " + ", ".join(live))
        name = self.name
        if self.team_store is not None:
            self.team_store.delete(name)
        if self.tasks is not None:
            shutil.rmtree(self.tasks.directory, ignore_errors=True)
        self.team_context = None

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

    async def allocate_isolation(self, name: str) -> str:
        if self.isolation_start is None:
            raise ValueError("isolation needs a provider: this team was given no isolation_start")
        return str(await self.isolation_start(name))

    async def release_isolation(self, agent_id: str) -> str:
        path = self._agent_isolation.pop(agent_id, None)
        if path is None or self.isolation_end is None:
            return ""
        return str(await self.isolation_end(path))

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

    def set_output_schema(self, schema: dict) -> str:
        problem = schema_problem(schema)
        if problem:
            return problem
        self.output_schema = schema
        self.structured_output = None
        self._output_attempts = 0
        if self._output_hook is None:
            self._output_hook = self.hooks.register(
                "Stop",
                "*",
                fn=self._output_is_missing,
                error_message=f"Call {STRUCTURED_OUTPUT_TOOL} now with your final answer in the required shape.",
            )
        return ""

    def _output_is_missing(self, request: dict) -> bool:
        if self.structured_output is not None:
            return True
        if self._output_attempts >= retries():
            return True
        self._output_attempts += 1
        return False

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

    def turn_metrics(self) -> Metrics:
        return self.lead.last_metrics

    def total_metrics(self) -> Metrics:
        total = Metrics()
        for agent in self.agents.values():
            total = total + agent.total_metrics
        return total

    def request_shutdown(self, agent_id: str):
        agent = self.agents.get(agent_id)
        if agent is not None:
            asyncio.get_running_loop().create_task(agent.stop())
