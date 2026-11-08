from __future__ import annotations

import asyncio
from pathlib import Path

from chatchat.tasks.task_list import TaskList
from chatchat.tool import ToolContext
from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.agent import Agent
from chatchat.runtime.agent_definition import (
    GENERAL_PURPOSE,
    AgentDefinition,
    AgentRegistry,
)
from chatchat.runtime.compaction import Compactor
from chatchat.runtime.config import RuntimeConfig
from chatchat.runtime.conversation import Conversation
from chatchat.runtime.background_tasks import BackgroundTasks
from chatchat.runtime.enums import CompletionStatus, IdleReason
from chatchat.runtime.mailbox import idle_notification as _idle_msg
from chatchat.runtime.sandbox import Sandbox
from chatchat.runtime.services import RuntimeServices
from chatchat.runtime.ledger import Ledger
from chatchat.runtime.model import ModelChoice
from chatchat.runtime.product import TeamProduct
from chatchat.runtime.roster import Roster
from chatchat.runtime.tool_surface import ToolSurface
from chatchat.runtime.context import AgentContext
from chatchat.runtime.filehistory import FileHistory
from chatchat.runtime.skills import SkillRegistry
from chatchat.runtime.thinking import Thinking
from chatchat.runtime.subagents import SubagentsMixin
from chatchat.tools.registry import ToolRegistry
from chatchat.tools.tool_runner import ToolRunnerMixin
from chatchat.hooks.events import AGENT_WARN, emit
from chatchat.hooks.executors import EVALUATOR_INSTRUCTION
from chatchat.hooks.manager import HookManager

LEAD_NAME = "team-lead"


class Runtime(SubagentsMixin, ToolRunnerMixin):
    """The execution core: one lead agent, its tools, hooks and conversation.

    A Team is this core plus collaboration. A single-agent run is this core on
    its own; it does not need a roster of teammates to execute.
    """

    multi_agent = False

    def __init__(self, name: str, config: RuntimeConfig | None = None):
        config = config or RuntimeConfig()
        self.name = name
        self.lead_session_id = ""
        self._model_timeout = config.model_timeout
        self._model_retries = config.model_retries
        self.model_choice = ModelChoice.from_config(config.model)
        self.tools = ToolSurface(owner=self, injected=config.tools)
        self.tool_context = config.tool_context or ToolContext(cwd=Path.cwd())
        self.tool_context.team = self
        self.instruction_files: list[dict] = []
        self.tasks = TaskList(Path(config.tasks_dir) / name) if config.tasks_dir else None
        self._file_history = (
            FileHistory(Path(config.file_history_dir), cwd=self.tool_context.cwd) if config.file_history_dir else None
        )
        self.tool_context.files = self._file_history

        self.skills = config.skills or SkillRegistry()
        self.services = config.services or RuntimeServices()
        self.user_input = self.services.user_input
        self.tool_policy = self.services.tool_policy
        self.agent_memory = config.agent_memory
        self.rules = config.rules
        self.sandbox = self.services.sandbox or Sandbox()
        self.product: TeamProduct | None = None
        self.background_tasks = self.services.background_tasks or BackgroundTasks()
        self._factory = config.model.client_factory
        self.hooks = HookManager(
            self,
            enabled=config.hooks,
            make_client=self._hook_client,
            spawn_agent=self._hook_agent,
        )
        self.roster = Roster(self.name)
        self._counter = 0
        self.context_window = int(config.context_window or 0)
        self.compactor = Compactor(
            summarize=self._summarize,
            hooks=self.hooks,
            window=self.context_window,
            reserve=config.compact_reserve,
            on_compacted=self.reset_rules,
        )
        self.sidechain_dir = config.sidechain_dir
        self.agent_defs = AgentRegistry()
        self.agent_defs.define(
            GENERAL_PURPOSE,
            tools=self.tools.injected,
            default=True,
            description="General-purpose agent that inherits the run tools for routine tasks",
        )
        self.lead = self.create_agent(LEAD_NAME, instruction=config.instruction, leader=True)
        self.ledger = Ledger(lead=self.lead, members=lambda: self.roster.agents.values())
        self.conversation = Conversation(
            lead=self.lead,
            hooks=self.hooks,
            tool_context=self.tool_context,
            history=self._file_history,
        )

    def attach(self, product: TeamProduct) -> TeamProduct:
        self.product = product
        return product

    def set_user_input(self, callback) -> None:
        self.user_input = callback

    def set_policy_mode(self, mode: str) -> None:
        self.hooks.permission_mode = mode

    def _inbox_for(self, name: str):
        return None

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

    def _hook_client(self, model: str | None):
        """The client a prompt hook judges its condition with."""
        return self._client_for(EVALUATOR_INSTRUCTION, thinking=Thinking("off"), model=model)

    async def _hook_agent(self, parent_name: str, instruction: str):
        """The agent an agent hook judges its condition in."""
        return await self.spawn_child(parent_name, instruction, internal=True)

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
        agent = Agent(
            agent_id,
            name,
            self,
            self._client_for(instruction, model=model),
            ctx,
            instruction=instruction,
            inbox=self._inbox_for(name),
            depth=depth,
            model_timeout=self._model_timeout,
            model_retries=self._model_retries,
        )
        self.roster.add(agent)
        agent.start()
        return agent

    def add(self, name: str, instruction: str = "") -> Agent:
        return self.create_agent(name, instruction=instruction)

    def set_instruction_files(self, files: list[dict]):
        self.instruction_files = list(files or [])

    def set_instruction(self, instruction: str):
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
    def file_history(self):
        return self.conversation.history

    @property
    def tool_registry(self) -> ToolRegistry:
        return self.tools.registry()

    def tool_schemas(self, context) -> list[dict]:
        return self.tools.schemas(context)

    @property
    def provided_tools(self):
        return self.tools.provided()

    def set_cwd(self, path):
        cwd = Path(path)
        self.tool_context.cwd = cwd
        self.hooks.set_cwd(cwd)
        if self.file_history is not None:
            self.file_history.cwd = cwd
        if self.product is not None:
            self.product.cwd_changed(cwd)

    def send_control(self, recipient_name: str, payload: str):
        recipient = self.get_by_name(recipient_name)
        if recipient is not None and recipient.inbox is not None:
            recipient.inbox.write(self.lead.agent_id, payload)

    async def notify_idle(
        self,
        agent: Agent,
        *,
        reason: IdleReason | str = IdleReason.AVAILABLE,
        summary: str = "",
        completed_task_id: str = "",
        completed_status: CompletionStatus | str = CompletionStatus.RESOLVED,
        failure_reason: str | None = None,
    ):
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None and agent.agent_id != lead.agent_id and lead.inbox is not None:
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
        if reason == IdleReason.FAILED and failure_reason:
            emit(AGENT_WARN, agent=agent.name, text=failure_reason)

    def request_shutdown(self, agent_id: str):
        agent = self.roster.get(agent_id)
        if agent is not None:
            asyncio.get_running_loop().create_task(agent.stop())
