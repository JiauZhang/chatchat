from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import chatchat.core.tools as _tools
from chatchat.tool import (ToolContext, ToolOutcome, ToolResult,
                           describe_tools)
from chatchat.core.abort import AbortSignal
from chatchat.core.agent import Agent
from chatchat.core.agents import GENERAL_PURPOSE, AgentDefinition, AgentRegistry
from chatchat.core.mailbox import FileMailbox
from chatchat.core.context import AgentContext
from chatchat.core.filehistory import FileHistory
from chatchat.core.mailbox import idle_notification as _idle_msg
from chatchat.core.tasks import TaskList
from chatchat.core.team_store import TeamStore
from chatchat.core.worktrees import (create, generated_name, in_repository,
                     remove)
from chatchat.core.skills import SkillRegistry, listing_budget
from chatchat.core.structured import (STRUCTURED_OUTPUT_TOOL, retries,
                                       schema_problem)
from chatchat.hooks.events import (AGENT_PROGRESS, AGENT_TOOL_RESULT,
                                  emit)
from chatchat.hooks.manager import HookManager

LEAD_NAME = 'team-lead'


def _tool_calls(agent: Agent) -> int:
    return sum(1 for message in agent.messages
               if isinstance(message.get('content'), list)
               for block in message['content']
               if isinstance(block, dict) and block.get('type') == 'tool_use')


DEFAULT_COMPACT_RESERVE = 40_000


def token_count(messages: list[dict]) -> int:
    for message in reversed(messages):
        usage = message.get('usage')
        if isinstance(usage, dict):
            return (int(usage.get('prompt_tokens', 0))
                    + int(usage.get('completion_tokens', 0)))
    return 0


class Team:
    def __init__(self, name: str, client=None, hooks: bool = True,
                 client_factory=None,
                 lead_instruction: str = '', model_timeout: float = 120.0,
                 model_retries: int = 2,
                 provider: str = None, model: str = None,
                 thinking: bool = True, tools: list = None,
                 tool_context: ToolContext = None,
                 context_window: int = 0,
                 compact_reserve: int = DEFAULT_COMPACT_RESERVE,
                 mailbox_dir=None, sidechain_dir=None, tasks_dir=None,
                 file_history_dir=None, skills=None, team_store=None,
                 multi_agent: bool = True, **client_kw):
        self.name = name
        self.multi_agent = multi_agent
        self._client = client
        self._model_timeout = model_timeout
        self._model_retries = model_retries
        self._provider = provider
        self._model = model
        self._thinking = thinking
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
        self.worktree: dict | None = None
        self.ask_user = None
        self.output_schema: dict | None = None
        self.structured_output: dict | None = None
        self._output_attempts = 0
        self._output_hook = None
        self._cwd_changed = None
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
        client = self._client_for('Summarize the conversation so far.')
        text = await client.respond(middle)
        if not isinstance(text, str) or not text.strip():
            return messages
        marker = {'role': 'user',
                  'content': f'[conversation summary]\n{text}'}
        return head + [marker] + tail

    async def maybe_compact(self, messages: list[dict], force: bool = False) -> list[dict]:
        if not force and (not self.auto_compact
                          or token_count(messages) < self._compact_threshold):
            return messages
        trigger = 'manual' if force else 'auto'
        await self.hooks.execute_pre_compact_hooks(trigger=trigger)
        result = self._compact_fn(messages)
        if asyncio.iscoroutine(result):
            result = await result
        emit('agent.compact', agent='',
             before=len(messages), after=len(result or []))
        await self.hooks.execute_post_compact_hooks(trigger=trigger)
        return list(result) if result else messages

    def _client_for(self, instruction: str, thinking: bool | None = None,
                    model: str | None = None):
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

    async def _start_subagent(self, prompt: str, subagent_type: str | None,
                              instruction: str, model, depth: int,
                              fork_msgs: list | None, tool_use_id: str):
        defn = self.agent_defs.get(subagent_type)
        sys_prompt = '\n'.join(p for p in (defn.full_prompt(), instruction)
                               if p) or defn.system_prompt
        from chatchat.core.task import rand_name
        name = rand_name(f'sub-{self._counter}')
        self._counter += 1
        agent_id = self.agent_id(name)
        abort = AbortSignal()
        ctx = AgentContext(agent_id=agent_id, agent_name=name,
                           team_name=self.name, abort=abort, leader=False)
        writer = None
        if self.sidechain_dir is not None:
            from chatchat.core.sidechain import SidechainWriter
            writer = SidechainWriter(self.sidechain_dir, name, self.name,
                                     subagent_type or '', prompt)
        model = model or defn.model
        agent = Agent(agent_id, name, self,
                      self._client_for(sys_prompt, model=model),
                      ctx, instruction=sys_prompt,
                      depth=depth, internal=True, tools=list(defn.tools),
                      model_timeout=self._model_timeout, model_retries=self._model_retries,
                      on_message=None if writer is None else writer.append,
                      agent_type=subagent_type or '')
        self.agents[agent_id] = agent
        if fork_msgs:
            agent.messages = list(fork_msgs)
        emit(AGENT_PROGRESS, agent=agent.name,
             prompt=prompt, subagent_type=subagent_type or '',
             tool_use_id=tool_use_id, started_at=time.time())
        start = await self.hooks.execute_subagent_start_hooks(
            agent, defn.agent_type)
        if start.additional_context:
            message = {'role': 'user', 'content': start.additional_context}
            agent.messages.append(message)
            agent._record(message)
        return agent, writer, defn

    async def _run_subagent(self, agent: Agent, prompt: str, writer,
                            defn) -> str:
        try:
            result = await agent.chat(prompt)
            if writer is not None:
                writer.finish('completed')
        except BaseException:
            if writer is not None:
                writer.finish('failed')
            raise
        finally:
            emit(AGENT_PROGRESS, agent=agent.name, done=True)
            await self.hooks.execute_subagent_stop_hooks(agent, defn.agent_type)
            agent._finalize('completed')
        return result

    async def spawn_subagent(self, prompt: str, *, subagent_type: str | None = None,
                             instruction: str = '', model=None, depth: int = 0,
                             fork_msgs: list | None = None,
                             tool_use_id: str = '') -> str:
        agent, writer, defn = await self._start_subagent(
            prompt, subagent_type, instruction, model, depth, fork_msgs,
            tool_use_id)
        return await self._run_subagent(agent, prompt, writer, defn)

    async def spawn_background_subagent(self, prompt: str, parent: Agent,
                                        *, subagent_type: str | None = None,
                                        instruction: str = '', model=None,
                                        depth: int = 0,
                                        fork_msgs: list | None = None,
                                        tool_use_id: str = '') -> str:
        agent, writer, defn = await self._start_subagent(
            prompt, subagent_type, instruction, model, depth, fork_msgs,
            tool_use_id)
        self.parents[agent.agent_id] = parent.agent_id
        self.children.setdefault(parent.agent_id, set()).add(agent.agent_id)
        task = asyncio.get_running_loop().create_task(
            self._report_to(agent, prompt, writer, defn, parent))
        self.background[agent.agent_id] = task
        task.add_done_callback(
            lambda done: self.background.pop(agent.agent_id, None))
        return agent.agent_id

    async def _report_to(self, agent: Agent, prompt: str, writer, defn,
                         parent: Agent):
        started = time.monotonic()
        status = 'completed'
        try:
            answer = await self._run_subagent(agent, prompt, writer, defn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status, answer = 'failed', str(exc)
        parent.inbox.write(
            agent.name,
            f'{agent.name}, the sub-agent you sent to the background, is '
            f'done.\nstatus: {status} \u00b7 tool calls: '
            f'{_tool_calls(agent)} \u00b7 tokens: '
            f'{agent.total_usage.total_tokens} \u00b7 '
            f'{time.monotonic() - started:.0f}s\n{answer}')

    async def spawn_child(self, parent_name: str, instruction: str, *,
                          internal: bool = True) -> Agent:
        from chatchat.core.task import rand_name
        self._counter += 1
        name = rand_name('hook')
        agent_id = self.agent_id(name)
        ctx = AgentContext(agent_id=agent_id, agent_name=name,
                           team_name=self.name, abort=AbortSignal(),
                           leader=False)
        return Agent(agent_id, name, self, self._client_for(instruction),
                     ctx, instruction=instruction, internal=internal,
                     hookless=True, model_timeout=self._model_timeout, model_retries=self._model_retries)

    async def stop_agent(self, agent: Agent):
        agent_id = agent.agent_id
        parent = self.parents.pop(agent_id, None)
        if parent and agent_id in self.children.get(parent, set()):
            self.children[parent].discard(agent_id)
            if not agent._internal:
                await self.hooks.execute_subagent_stop_hooks(
                    agent, agent.agent_type)
        await agent.stop()
        if self.team_store is not None and self.team_context is not None:
            self.team_store.drop_member(self.name, agent_id)
        if self.tasks is not None and not agent._internal:
            released = self.tasks.unassign(agent_id, agent.name)
            if released and agent is not self.lead:
                self.lead.inbox.write(
                    agent.name,
                    f'{agent.name} stopped with '
                    f'{len(released)} task(s) handed back: '
                    + ', '.join(f'#{t.id} {t.subject}' for t in released)
                    + '. Give them to another agent or pick them up yourself.')

    async def wait_for_idle(self, agent_id: str, timeout: float | None = None):
        agent = self.agents.get(agent_id)
        if agent is None:
            return
        await agent.wait_idle(timeout)

    async def reclaim(self, agent: Agent, prompt: str,
                      timeout: float | None = None) -> str:
        agent.submit(prompt)
        await agent.wait_idle(timeout)
        return last_assistant(agent)

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

    def set_instruction_files(self, files: list[dict]):
        self.instruction_files = list(files or [])

    def set_lead_instruction(self, instruction: str):
        lead = self.get_by_name(LEAD_NAME)
        if lead is None:
            return
        lead.instruction = instruction
        lead.client = self._client_for(instruction)

    def set_thinking(self, on: bool):
        self._thinking = bool(on)
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

    def tool_schemas(self, context: ToolContext) -> list[dict]:
        team_tools = [
            {'name': 'create_agent',
             'description': self._create_agent_description(),
             'input_schema': {'type': 'object',
                              'properties': {'prompt': {'type': 'string'},
                                             'instruction': {'type': 'string'},
                                             'subagent_type': {'type': 'string'},
                                             'name': {'type': 'string',
                                                      'description': 'Optional '
                                                      'name for a persistent '
                                                      'teammate (team mode): '
                                                      'stays alive with a '
                                                      'mailbox; message it via '
                                                      'send_message. Omit for '
                                                      'a one-off sub-agent.'},
                                             'model': {'type': 'string',
                                                       'description': 'Optional '
                                                       'model override for the '
                                                       'spawned agent.'},
                                             'run_in_background': {
                                                 'type': 'boolean',
                                                 'description': 'Set true for a '
                                                 'one-off sub-agent whose work '
                                                 'should not hold this turn '
                                                 'open. The answer arrives in '
                                                 'your inbox when it finishes.'}},
                              'required': ['prompt']}},
        ]
        if self.multi_agent:
            team_tools += [
                {'name': 'send_message',
                 'description': 'Send a message to a teammate by name (or "*" to '
                                'broadcast). Messages are delivered to their mailbox '
                                'and injected on their next idle turn.',
                 'input_schema': {'type': 'object',
                                  'properties': {'to': {'type': 'string'},
                                                 'message': {'type': 'string'}},
                                  'required': ['to', 'message']}},
                {'name': 'task_stop',
                 'description': 'Permanently stop one of your own sub-agents.',
                 'input_schema': {'type': 'object',
                                  'properties': {'agent_id': {'type': 'string'}},
                                  'required': ['agent_id']}},
                {'name': 'team_create',
                 'description': 'Gather the work under one named team. The '
                                'team and its task list are the same thing: '
                                'every task you create from now on belongs to '
                                'it, and so does every teammate you spawn. '
                                'Call it once, before the work is divided.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'team_name': {'type': 'string'},
                                      'description': {'type': 'string'}},
                                  'required': ['team_name']}},
                {'name': 'team_delete',
                 'description': 'Throw away the current team and its task list '
                                'once the work is done. It refuses while a '
                                'teammate is still running, so stop them '
                                'first with task_stop.',
                 'input_schema': {'type': 'object', 'properties': {}}},
            ]
        if self.tasks is not None:
            team_tools += [
                {'name': 'task_create',
                 'description': 'Add a task to the team list so the work is '
                                'tracked and claimable. Use it for anything '
                                'with more than one step; give a short '
                                'imperative subject and the full description.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'subject': {'type': 'string'},
                                      'description': {'type': 'string'},
                                      'active_form': {
                                          'type': 'string',
                                          'description': 'Present continuous '
                                          'label shown while it is running'},
                                      'metadata': {'type': 'object'}},
                 'required': ['subject', 'description']}},
                {'name': 'task_list',
                 'description': 'List every task with its status, owner and '
                                'open blockers. Check it before creating so '
                                'work is not duplicated.',
                 'input_schema': {'type': 'object', 'properties': {}}},
                {'name': 'task_get',
                 'description': 'Read one task in full.',
                 'input_schema': {'type': 'object',
                                  'properties': {'task_id': {'type': 'string'}},
                                  'required': ['task_id']}},
                {'name': 'task_update',
                 'description': 'Change a task: move it through pending, '
                                'in_progress and completed, hand it to an '
                                'owner, or link it with add_blocks / '
                                'add_blocked_by. status "deleted" removes it. '
                                'Mark a task in_progress before starting it.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'task_id': {'type': 'string'},
                                      'subject': {'type': 'string'},
                                      'description': {'type': 'string'},
                                      'active_form': {'type': 'string'},
                                      'status': {'type': 'string',
                                                 'enum': ['pending',
                                                          'in_progress',
                                                          'completed',
                                                          'deleted']},
                                      'owner': {'type': 'string'},
                                      'metadata': {'type': 'object'},
                                      'add_blocks': {'type': 'array',
                                                     'items': {
                                                         'type': 'string'}},
                                      'add_blocked_by': {'type': 'array',
                                                         'items': {
                                                             'type': 'string'}}},
                                  'required': ['task_id']}},
            ]
        if self.ask_user is not None:
            team_tools.append(
                {'name': 'ask_user',
                 'description': 'Ask the human one to four questions and wait '
                                'for the answers, when a choice they can make '
                                'would change what you do. Give each question '
                                'two to four options worth picking; they can '
                                'also answer in their own words.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'questions': {
                                          'type': 'array',
                                          'items': {
                                              'type': 'object',
                                              'properties': {
                                                  'question': {'type': 'string'},
                                                  'header': {'type': 'string'},
                                                  'multiSelect': {
                                                      'type': 'boolean'},
                                                  'options': {
                                                      'type': 'array',
                                                      'items': {
                                                          'type': 'object',
                                                          'properties': {
                                                              'label': {
                                                                  'type': 'string'},
                                                              'description': {
                                                                  'type': 'string'}},
                                                          'required': ['label']}}},
                                              'required': ['question',
                                                          'options']}}},
                                  'required': ['questions']}})
        if self._worktrees:
            team_tools += [
                {'name': 'enter_worktree',
                 'description': 'Only when the user asks for a worktree: make '
                                'an isolated git worktree under '
                                '.pyclaw/worktrees and move this session into '
                                'it, so the work cannot touch the checked-out '
                                'directory. Refuses outside a git repository.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'name': {'type': 'string',
                                               'description': 'Optional; a '
                                                              'random one is '
                                                              'picked.'}}}},
                {'name': 'exit_worktree',
                 'description': 'Leave the worktree this session moved into, '
                                'back to the original directory. action '
                                '"remove" also throws the worktree away, '
                                'keeping its branch.',
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'action': {'type': 'string',
                                                 'enum': ['keep', 'remove']}}}},
            ]
        skills = self.skills.all()
        if skills:
            team_tools.append(
                {'name': 'use_skill',
                 'description': 'Load the full instructions of one skill when '
                                'the task at hand is one it covers. The '
                                'listing below only says what each skill is '
                                'for; the steps come from this call.\n\n'
                                'Available skills:\n'
                                + self.skills.listing(
                                    listing_budget(self.context_window)),
                 'input_schema': {'type': 'object',
                                  'properties': {
                                      'skill': {'type': 'string',
                                                'description': 'The name from '
                                                               'the listing.'},
                                      'args': {'type': 'string',
                                               'description': 'What the skill '
                                                              'should work on.'}},
                                  'required': ['skill']}})
        if self.output_schema is not None:
            team_tools.append(
                {'name': STRUCTURED_OUTPUT_TOOL,
                 'description': 'Return your final answer as the structured '
                                'payload below. Call it exactly once, at the '
                                'end of the work; nothing you say in prose '
                                'counts as the answer.\n\nThe payload must '
                                'match this schema.',
                 'input_schema': self.output_schema})
        return team_tools + describe_tools(self._injected_tools, context)

    async def _post_tool_context(self, agent, tool_use_id: str, name: str,
                                 input: dict, value,
                                 failed: bool = False) -> str:
        if agent is None or agent.hookless:
            return ''
        if failed:
            agg = await self.hooks.execute_post_tool_failure_hooks(
                agent, tool_use_id, name, input, value)
        else:
            agg = await self.hooks.execute_post_tool_hooks(
                agent, tool_use_id, name, input, value)
        return agg.additional_context

    def _changed_file(self, tool, input: dict) -> str:
        if tool is None or tool.read_only or tool.get_path is None:
            return ''
        raw = tool.get_path(input)
        if not raw:
            return ''
        cwd = Path(self.tool_context.cwd).resolve()
        path = Path(str(raw)).expanduser()
        path = path if path.is_absolute() else cwd / path
        path = path.resolve()
        return str(path) if path.is_relative_to(cwd) else ''

    async def _note_file_changed(self, agent, tool, input: dict) -> str:
        path = self._changed_file(tool, input)
        if not path or agent is None or agent.hookless:
            return ''
        agg = await self.hooks.execute_file_changed_hooks(agent, path)
        return agg.additional_context

    async def execute_tool(self, name: str, input: dict, agent: Agent,
                           tool_use_id: str = '') -> ToolOutcome:
        pool = self._injected_tools if (agent is None
                                        or agent.tools is None) else agent.tools
        team_fns = ({} if agent is not None and agent.tools is not None
                    else {'send_message': _tools.send_message,
                          'create_agent': _tools.create_agent,
                          'task_stop': _tools.task_stop})
        if self.tasks is not None:
            team_fns |= {'task_create': _tools.task_create,
                         'task_list': _tools.task_list,
                         'task_get': _tools.task_get,
                         'task_update': _tools.task_update}
        if self.multi_agent:
            team_fns |= {'team_create': _tools.team_create,
                         'team_delete': _tools.team_delete}
        if self.skills.all():
            team_fns['use_skill'] = _tools.use_skill
        if self._worktrees:
            team_fns |= {'enter_worktree': _tools.enter_worktree,
                         'exit_worktree': _tools.exit_worktree}
        if self.ask_user is not None:
            team_fns['ask_user'] = _tools.ask_user
        if self.output_schema is not None:
            team_fns[STRUCTURED_OUTPUT_TOOL] = _tools.structured_output
        extra = ''
        if agent is not None and not agent.hookless:
            pre = await self.hooks.execute_pre_tool_hooks(
                agent, tool_use_id, name, input)
            if pre.blocking_error is not None:
                return ToolOutcome(
                    f'Error: hook blocked tool "{name}": '
                    f'{pre.blocking_error.blocking_error}')
            if pre.updated_input is not None:
                input = {**input, **pre.updated_input}
            extra = pre.additional_context
        fn = team_fns.get(name)
        if fn is None:
            tool = next((t for t in pool if t.name == name), None)
            if tool is None:
                return ToolOutcome(
                    f'Error: tool "{name}" is not available to this agent',
                    extra)
            try:
                out = await tool(agent.tool_context, **input)
                if isinstance(out, ToolResult):
                    emit(AGENT_TOOL_RESULT,
                         agent=getattr(agent, 'name', ''),
                         tool=name, tool_use_id=tool_use_id,
                         **(out.meta or {}))
                    out = out.text
                elif not isinstance(out, str):
                    out = str(out)
            except Exception as e:
                return ToolOutcome(
                    f'Error calling tool "{name}": {type(e).__name__}: {e}',
                    _joined(extra, await self._post_tool_context(
                        agent, tool_use_id, name, input, e, True)))
            return ToolOutcome(out, _joined(extra, await self._post_tool_context(
                agent, tool_use_id, name, input, out),
                await self._note_file_changed(agent, tool, input)))
        try:
            out = await fn(self, agent, input, tool_use_id)
        except Exception as e:
            return ToolOutcome(
                f'Error calling tool "{name}": {type(e).__name__}: {e}',
                _joined(extra, await self._post_tool_context(
                    agent, tool_use_id, name, input, e, True)))
        return ToolOutcome(out, _joined(extra, await self._post_tool_context(
            agent, tool_use_id, name, input, out)))

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

    def request_shutdown(self, agent_id: str):
        agent = self.agents.get(agent_id)
        if agent is not None:
            asyncio.get_running_loop().create_task(agent.stop())


def _joined(*parts: str) -> str:
    return '\n'.join(p for p in parts if p)


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


def create_team(name: str, client=None, client_factory=None,
                lead_instruction: str = '', **kw) -> Team:
    return Team(name, client=client, client_factory=client_factory,
                lead_instruction=lead_instruction, **kw)
