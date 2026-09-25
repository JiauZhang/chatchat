from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from chatchat.tool import ToolContext
from chatchat.core.abort import AbortSignal
from chatchat.core.agent import Agent
from chatchat.core.agents import (
    GENERAL_PURPOSE,
    AgentDefinition,
    AgentRegistry,
)
from chatchat.core.mailbox import FileMailbox
from chatchat.core.metrics import Metrics
from chatchat.core.context import AgentContext
from chatchat.core.filehistory import FileHistory
from chatchat.core.mailbox import idle_notification as _idle_msg
from chatchat.core.tasks import TaskList
from chatchat.core.team_store import TeamStore
from chatchat.core.worktrees import (
    create,
    generated_name,
    in_repository,
    remove,
)
from chatchat.core.skills import SkillRegistry
from chatchat.core.thinking import Thinking
from chatchat.core.standing import with_standing
from chatchat.core.tokens import context_estimate, measured
from chatchat.core.subagents import SubagentsMixin
from chatchat.core.tool_runner import ToolRunnerMixin
from chatchat.core.tool_schemas import TeamSchemasMixin
from chatchat.core.structured import (
    STRUCTURED_OUTPUT_TOOL,
    retries,
    schema_problem,
)
from chatchat.hooks.events import AGENT_COMPACT, emit
from chatchat.hooks.manager import HookManager

LEAD_NAME = 'team-lead'


DEFAULT_COMPACT_RESERVE = 40_000
MAX_COMPACT_FAILURES = 3


def last_assistant(agent: Agent, *, start: int = 0) -> str:
    for m in reversed(agent.messages[start:]):
        if not isinstance(m, dict):
            continue
        if m.get('role') == 'assistant' and isinstance(m.get('content'), str):
            return m['content']
    for m in reversed(agent.messages):
        if not isinstance(m, dict) or m.get('role') != 'user':
            continue
        content = m.get('content')
        if isinstance(content, list):
            for b in content:
                if b.get('type') == 'tool_result' and isinstance(b.get('content'), str):
                    return b['content']
    return ''


def _note_compaction(agent, *, failed: bool) -> None:
    if agent is None:
        return
    agent.compact_failures = (agent.compact_failures + 1 if failed else 0)


SUMMARY_MARK = '[conversation summary]'


def summary_of(messages: list[dict]) -> str:
    for message in messages:
        content = message.get('content')
        if isinstance(content, str) and content.startswith(SUMMARY_MARK):
            return content[len(SUMMARY_MARK):].strip()
    return ''


def token_count(messages: list[dict]) -> int:
    for message in reversed(messages):
        usage = message.get('usage')
        if isinstance(usage, dict):
            return measured(usage)
    return 0


class Team(SubagentsMixin, TeamSchemasMixin, ToolRunnerMixin):
    def __init__(self, name: str, client=None, hooks: bool = True,
                 client_factory=None,
                 lead_instruction: str = '', model_timeout: float = 120.0,
                 model_retries: int = 2,
                 provider: str = None, model: str = None,
                 thinking: Thinking | None = None,
                 tools: list = None,
                 tool_context: ToolContext = None,
                 context_window: int = 0,
                 compact_reserve: int = DEFAULT_COMPACT_RESERVE,
                 mailbox_dir=None, sidechain_dir=None, tasks_dir=None,
                 file_history_dir=None, skills=None, team_store=None,
                 agent_memory=None, cron=None, rules=None,
                 multi_agent: bool = True, **client_kw):
        self.name = name
        self.multi_agent = multi_agent
        self._client = client
        self._model_timeout = model_timeout
        self._model_retries = model_retries
        self._provider = provider
        self._model = model
        self._thinking = thinking or Thinking.from_env()
        self._client_kw = client_kw
        self._injected_tools = list(tools or [])
        self.tool_context = tool_context or ToolContext(cwd=Path.cwd())
        self.instruction_files: list[dict] = []
        self._mailbox_root = Path(mailbox_dir) if mailbox_dir else None
        self._tasks_root = Path(tasks_dir) if tasks_dir else None
        self.team_store = TeamStore(Path(team_store)) if team_store else None
        self.team_context: dict | None = None
        self._mailbox_dir = self._team_mailbox_dir()
        self.tasks = (TaskList(self._tasks_root / self.name)
                      if self._tasks_root else None)
        self.file_history = (FileHistory(
            Path(file_history_dir) / self.name, cwd=self.tool_context.cwd)
            if file_history_dir else None)
        self.tool_context.files = self.file_history
        self.skills = skills or SkillRegistry()
        self.agent_memory = agent_memory
        self.cron = cron
        self.rules = rules
        self.worktree: dict | None = None
        self.ask_user = None
        self.output_schema: dict | None = None
        self.structured_output: dict | None = None
        self._output_attempts = 0
        self._output_hook = None
        self._cwd_changed = None
        self._plan_mode_changed = None
        self.plan_path = None
        self._worktrees = in_repository(self.tool_context.cwd)
        self._factory = client_factory
        self.hooks = HookManager(self, enabled=hooks)
        self.agents: dict[str, Agent] = {}
        self.background: dict[str, asyncio.Task] = {}
        self.children: dict[str, set[str]] = {}
        self.parents: dict[str, str] = {}
        self._counter = 0
        self._session_started = False
        self._session_setup_done = False
        self._session_source = 'startup'
        self.context_window = int(context_window or 0)
        self._compact_threshold = max(0, self.context_window
                                       - int(compact_reserve))
        self.sidechain_dir = sidechain_dir
        self._compact_fn = self._builtin_compact
        self.agent_defs = AgentRegistry()
        self.agent_defs.define(GENERAL_PURPOSE,
                               tools=list(self._injected_tools), default=True,
                               description='General-purpose agent that '
                                           'inherits the team tools for '
                                           'routine tasks')
        self.lead = self.create_agent(LEAD_NAME, instruction=lead_instruction,
                                      leader=True)

    def register_agent_definition(self, defn) -> AgentDefinition:
        return self.agent_defs.register(defn)

    def remove_agent_definition(self, agent_type: str) -> bool:
        return self.agent_defs.remove(agent_type)

    def define_agent(self, agent_type: str, *, system_prompt: str = '',
                     tools: list = None, model: str | None = None,
                     addenda: str = '', default: bool = False) -> AgentDefinition:
        return self.agent_defs.define(agent_type, system_prompt=system_prompt,
                                      tools=tools, model=model, addenda=addenda,
                                      default=default)

    async def compact(self, messages: list[dict], force: bool = False) -> list[dict]:
        return await self.maybe_compact(messages, force=force)

    async def _builtin_compact(self, messages: list[dict]) -> list[dict]:
        keep_recent = 8
        if len(messages) <= keep_recent + 2:
            return messages
        head, tail = messages[:2], messages[-keep_recent:]
        middle = messages[2:-keep_recent]
        client = self._client_for('Summarize the conversation so far.',
                          standing=False)
        text = await client.respond(middle)
        if not isinstance(text, str) or not text.strip():
            return None
        marker = {'role': 'user',
                  'content': f'{SUMMARY_MARK}\n{text}'}
        return head + [marker] + tail

    async def maybe_compact(self, messages: list[dict], force: bool = False,
                            agent: Agent = None) -> list[dict]:
        failures = getattr(agent, 'compact_failures', 0)
        if not force and (agent is not None
                          and failures >= MAX_COMPACT_FAILURES):
            return messages
        if not force and (not self.auto_compact
                          or context_estimate(messages) < self._compact_threshold):
            return messages
        trigger = 'manual' if force else 'auto'
        await self.hooks.execute_pre_compact_hooks(trigger=trigger)
        try:
            result = self._compact_fn(messages)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception:
            _note_compaction(agent, failed=True)
            return messages
        if result is None:
            _note_compaction(agent, failed=True)
            return messages
        if len(result) >= len(messages):
            return list(result) if result else messages
        _note_compaction(agent, failed=False)
        self.reset_rules()
        emit(AGENT_COMPACT, agent='', before=len(messages),
             after=len(result), summarized=len(messages) - len(result) + 1,
             summary=summary_of(result))
        await self.hooks.execute_post_compact_hooks(trigger=trigger)
        return list(result)

    def _client_for(self, instruction: str, thinking: Thinking | None = None,
                    model: str | None = None, standing: bool = True):
        instruction = with_standing(instruction) if standing else instruction
        if self._factory is not None:
            return self._factory(instruction, model)
        if self._client is not None:
            return self._client
        from chatchat.client import Client
        return Client(self._provider, model=model or self._model,
                      instruction=instruction,
                      thinking=self._thinking if thinking is None else thinking,
                      **self._client_kw)

    def agent_id(self, name: str) -> str:
        return f'{name}@{self.name}'

    def get(self, agent_id: str) -> Agent | None:
        return self.agents.get(agent_id)

    def get_by_name(self, name: str) -> Agent | None:
        return self.agents.get(self.agent_id(name))

    def create_agent(self, name: str, instruction: str = '', model=None,
                     leader: bool = False, depth: int = 0) -> Agent:
        agent_id = self.agent_id(name)
        abort = AbortSignal()
        ctx = AgentContext(agent_id=agent_id, agent_name=name,
                           team_name=self.name, abort=abort, leader=leader)
        inbox = None
        if self._mailbox_dir is not None:
            inbox = FileMailbox(self.mailbox_path(name))
        agent = Agent(agent_id, name, self,
                      self._client_for(instruction, model=model),
                      ctx, instruction=instruction, inbox=inbox,
                      depth=depth, model_timeout=self._model_timeout, model_retries=self._model_retries)
        self.agents[agent_id] = agent
        agent.start()
        if self.team_store is not None and self.team_context is not None:
            self.team_store.note_member(self.name, {
                'agent_id': agent_id, 'name': name,
                'model': str(getattr(agent.client, 'model', '') or ''),
                'prompt': instruction})
        return agent

    def add(self, name: str, instruction: str = '') -> Agent:
        return self.create_agent(name, instruction=instruction)










    def transcript(self) -> list[dict]:
        return list(self.lead.messages)

    def restore(self, messages: list[dict]):
        self.lead.messages = [m for m in messages if isinstance(m, dict)]
        if self.lead.messages:
            self._session_source = 'resume'

    async def end_session(self, reason: str):
        await self.hooks.execute_session_end_hooks(reason)

    def begin_new_session(self, source: str = 'clear'):
        self._session_source = source
        self._session_started = False

    async def _open_session(self):
        aggs = []
        if not self._session_setup_done:
            self._session_setup_done = True
            aggs.append(await self.hooks.execute_setup_hooks())
        aggs.append(await self.hooks.execute_session_start_hooks(
            self._session_source))
        for agg in aggs:
            if agg.additional_context:
                self.lead.messages.append(
                    {'role': 'user', 'content': agg.additional_context})

    def usage(self):
        total = type(self.lead.total_usage)()
        for agent in self.agents.values():
            total.add(agent.total_usage)
        return total

    def last_usage(self):
        for message in reversed(self.transcript()):
            usage = message.get('usage')
            if isinstance(usage, dict):
                return type(self.lead.total_usage).from_dict(usage)
        return None

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
        return self._provider

    @property
    def model(self):
        return self._model

    @property
    def thinking(self):
        return self._thinking

    @property
    def provided_tools(self):
        return list(self._injected_tools)

    @property
    def compact_threshold(self) -> int:
        return int(self._compact_threshold or 0)

    @property
    def auto_compact(self) -> bool:
        return self._compact_fn is not None and self.context_window > 0

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
        return last_assistant(self.lead, start=start)

    def _team_mailbox_dir(self) -> Path | None:
        if self._mailbox_root is None:
            return None
        return self._mailbox_root / self.name / 'inboxes'

    def mailbox_path(self, member: str) -> Path:
        return self._mailbox_dir / f'{member}.json'

    def teammates(self) -> list:
        return [agent for agent in self.agents.values()
                if agent is not self.lead and not agent._internal
                and agent.is_running]

    def join_team(self, name: str, description: str = ''):
        if self.team_context is not None:
            raise ValueError(f'already in the team {self.name}')
        name = str(name or '').strip()
        if not name:
            raise ValueError('a team needs a name')
        if self.team_store is not None:
            self.team_store.create(name, description,
                                   leader=self.lead.agent_id)
        self.name = name
        self._mailbox_dir = self._team_mailbox_dir()
        self.tasks = (TaskList(self._tasks_root / name)
                      if self._tasks_root is not None else None)
        self.team_context = {'name': name, 'description': description}
        return self.team_context

    def leave_team(self):
        if self.team_context is None:
            return
        live = [agent.name for agent in self.teammates()]
        if live:
            raise ValueError('the team still has teammates: '
                             + ', '.join(live))
        name = self.name
        if self.team_store is not None:
            self.team_store.delete(name)
        if self.tasks is not None:
            shutil.rmtree(self.tasks.directory, ignore_errors=True)
        self.team_context = None

    def set_cwd(self, path):
        cwd = Path(path)
        self.tool_context.cwd = cwd
        if self.file_history is not None:
            self.file_history.cwd = cwd
        if self._cwd_changed is not None:
            self._cwd_changed(cwd)

    def set_plan_mode(self, mode: str) -> None:
        if self._plan_mode_changed is not None:
            self._plan_mode_changed(mode)
        else:
            self.hooks.permission_mode = mode

    async def enter_worktree(self, name: str = '') -> str:
        if self.worktree is not None:
            raise ValueError(f'already working in {self.worktree["name"]}')
        if not self._worktrees:
            return ('Error: this directory is not a git repository, so the '
                    'work cannot be isolated in a worktree.')
        name = str(name or '').strip() or generated_name()
        try:
            record = create(self.tool_context.cwd, name)
        except ValueError as exc:
            return f'Error: {exc}'
        self.worktree = record
        self.set_cwd(record['path'])
        await self.hooks.execute_worktree_create_hooks(self.lead, name)
        await self.hooks.execute_cwd_changed_hooks(self.lead,
                                                    str(record['path']))
        return (f'Working in {record["path"]} on branch {record["branch"]}. '
                f'The session directory moved with it.')

    async def exit_worktree(self, keep: bool = False) -> str:
        if self.worktree is None:
            return 'Error: this session is not in a worktree.'
        record = self.worktree
        self.worktree = None
        self.set_cwd(record['origin'])
        moved = ''
        if not keep:
            try:
                remove(record)
                moved = f' The worktree was removed; {record["branch"]} stays ' \
                        f'in the repository.'
            except ValueError as exc:
                moved = f' The worktree could not be removed: {exc}'
        await self.hooks.execute_worktree_remove_hooks(self.lead,
                                                       record['name'])
        await self.hooks.execute_cwd_changed_hooks(self.lead,
                                                   str(record['origin']))
        return f'Back at {record["origin"]}.' + moved

    def turns(self) -> list[tuple[int, str]]:
        if self.file_history is None:
            return []
        marks = {snap.mark for snap in self.file_history.snapshots}
        return [(index, str(message.get('content') or ''))
                for index, message in enumerate(self.lead.messages)
                if index in marks and message.get('role') == 'user']

    def rewind(self, mark: int, *, code: bool = True,
               conversation: bool = True) -> dict:
        files = (self.file_history.rewind(mark)
                 if code and self.file_history is not None else [])
        removed = 0
        if conversation:
            kept = self.lead.messages[:int(mark)]
            removed = len(self.lead.messages) - len(kept)
            self.lead.messages = list(kept)
        return {'files': files, 'messages': removed}

    def _create_agent_description(self) -> str:
        text = ('Run a one-off isolated sub-agent (AgentDefinition '
                'by subagent_type, default general-purpose): spawns a '
                'fresh agent, runs synchronously, returns its final '
                'answer, then is reclaimed. Not a teammate. With '
                'run_in_background it returns at once and the answer '
                'arrives as a message when that work is done.')
        lines = [f'- {agent_type}: {when_to_use}'
                 for agent_type, when_to_use in self.agent_defs.describe()]
        if lines:
            text += '\nAvailable subagent types:\n' + '\n'.join(lines)
        return text

    def set_output_schema(self, schema: dict) -> str:
        problem = schema_problem(schema)
        if problem:
            return problem
        self.output_schema = schema
        self.structured_output = None
        self._output_attempts = 0
        if self._output_hook is None:
            self._output_hook = self.hooks.register(
                'Stop', '*', fn=self._output_is_missing,
                error_message=f'Call {STRUCTURED_OUTPUT_TOOL} now with your '
                              f'final answer in the required shape.')
        return ''

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

    async def notify_idle(self, agent: Agent, *, reason: str = 'available',
                          summary: str = '', completed_task_id: str = '',
                          completed_status: str = 'resolved',
                          failure_reason: str | None = None):
        lead = self.get_by_name(LEAD_NAME)
        if lead is not None and agent.agent_id != lead.agent_id:
            lead.inbox.write(
                agent.agent_id,
                _idle_msg(agent.name, idle_reason=reason, summary=summary,
                          completed_task_id=completed_task_id,
                          completed_status=completed_status,
                          failure_reason=failure_reason or ''))
        if reason == 'failed' and failure_reason:
            from chatchat.hooks.events import AGENT_WARN
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


def create_team(name: str, client=None, client_factory=None,
                lead_instruction: str = '', **kw) -> Team:
    return Team(name, client=client, client_factory=client_factory,
                lead_instruction=lead_instruction, **kw)
