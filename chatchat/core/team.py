from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import chatchat.core.tools as _tools
from chatchat.core.abort import AbortSignal
from chatchat.core.agent import Agent
from chatchat.core.agents import GENERAL_PURPOSE, AgentDefinition, AgentRegistry
from chatchat.core.mailbox import FileMailbox
from chatchat.core.context import AgentContext
from chatchat.core.mailbox import idle_notification as _idle_msg
from chatchat.hooks.events import AGENT_PROGRESS, emit
from chatchat.hooks.manager import HookManager

LEAD_NAME = 'team-lead'


def _msgs_chars(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get('content')
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    total += len(b.get('content', '')) if isinstance(
                        b.get('content', ''), str) else 200
    return total


class Team:
    def __init__(self, name: str, client=None, hooks: bool = True,
                 client_factory=None,
                 lead_instruction: str = '', model_timeout: float = 120.0,
                 provider: str = None, model: str = None,
                 thinking: bool = True, tools: list = None,
                 compact_tokens: int = 160_000,
                 mailbox_dir=None,
                 multi_agent: bool = True, **client_kw):
        self.name = name
        self.multi_agent = multi_agent
        self._client = client
        self._model_timeout = model_timeout
        self._provider = provider
        self._model = model
        self._thinking = thinking
        self._client_kw = client_kw
        self._injected_tools = list(tools or [])
        self.instruction_files: list[dict] = []
        self._mailbox_dir = (Path(mailbox_dir) / self.name / 'inboxes'
                             if mailbox_dir else None)
        self._factory = client_factory
        self.hooks = HookManager(self, enabled=hooks)
        self.agents: dict[str, Agent] = {}
        self.children: dict[str, set[str]] = {}
        self.parents: dict[str, str] = {}
        self._counter = 0
        self._session_started = False
        self._compact_fn = None
        self._compact_threshold = compact_tokens
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

    def define_agent(self, agent_type: str, *, system_prompt: str = '',
                     tools: list = None, model: str | None = None,
                     addenda: str = '', default: bool = False) -> AgentDefinition:
        return self.agent_defs.define(agent_type, system_prompt=system_prompt,
                                      tools=tools, model=model, addenda=addenda,
                                      default=default)

    def set_compact_strategy(self, fn, *, threshold: int = 50_000):
        self._compact_fn = fn
        self._compact_threshold = threshold

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
        if not force and (self._compact_fn is None
                          or -(-_msgs_chars(messages) // 4) < self._compact_threshold):
            return messages
        await self.hooks.execute_pre_compact_hooks()
        result = self._compact_fn(messages)
        if asyncio.iscoroutine(result):
            result = await result
        emit('agent.compact', agent='',
             before=len(messages), after=len(result or []))
        await self.hooks.execute_post_compact_hooks()
        return list(result) if result else messages

    def _client_for(self, instruction: str, thinking: bool | None = None):
        if self._factory is not None:
            return self._factory(instruction)
        if self._client is not None:
            return self._client
        from chatchat.client import Client
        return Client(self._provider, model=self._model,
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
            inbox = FileMailbox(self._mailbox_dir / f'{name}.json')
        agent = Agent(agent_id, name, self, self._client_for(instruction),
                      ctx, instruction=instruction, inbox=inbox,
                      depth=depth, model_timeout=self._model_timeout)
        self.agents[agent_id] = agent
        agent.start()
        return agent

    def add(self, name: str, instruction: str = '') -> Agent:
        return self.create_agent(name, instruction=instruction)

    def spawn_teammate(self, name: str, prompt: str, *,
                       instruction: str = '', model=None,
                       parent: str = LEAD_NAME, depth: int = 0) -> Agent:
        self._counter += 1
        agent = self.create_agent(name, instruction=instruction, model=model,
                                  depth=depth)
        self.parents[agent.agent_id] = parent
        self.children.setdefault(parent, set()).add(agent.agent_id)
        if not agent._internal:
            asyncio.get_running_loop().create_task(
                self.hooks.execute_subagent_start_hooks(agent, parent))
        agent.submit(prompt)
        return agent

    async def spawn_subagent(self, prompt: str, *, subagent_type: str | None = None,
                             instruction: str = '', model=None, depth: int = 0,
                             fork_msgs: list | None = None) -> str:
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
        agent = Agent(agent_id, name, self, self._client_for(sys_prompt),
                      ctx, instruction=sys_prompt,
                      depth=depth, internal=True, tool_exec=defn,
                      model_timeout=self._model_timeout)
        if fork_msgs:
            agent.messages = list(fork_msgs)
        emit(AGENT_PROGRESS, agent=agent.name,
             prompt=prompt, subagent_type=subagent_type or '')
        try:
            return await agent.chat(prompt)
        finally:
            emit(AGENT_PROGRESS, agent=agent.name, done=True)
            await self.hooks.execute_subagent_stop_hooks(agent, LEAD_NAME)
            agent._finalize('completed')

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
                     hookless=True, model_timeout=self._model_timeout)

    async def stop_agent(self, agent: Agent):
        agent_id = agent.agent_id
        parent = self.parents.pop(agent_id, None)
        if parent and agent_id in self.children.get(parent, set()):
            self.children[parent].discard(agent_id)
            if not agent._internal:
                await self.hooks.execute_subagent_stop_hooks(agent, parent)
        await agent.stop()

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

    def usage(self):
        return self.lead.total_usage

    def reset_usage(self):
        self.lead.total_usage = type(self.lead.total_usage)()

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

    async def query(self, prompt: str, timeout: float | None = None) -> str:
        if not self._session_started:
            self._session_started = True
            await self.hooks.execute_setup_hooks()
            await self.hooks.execute_session_start_hooks()
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

    def _create_agent_description(self) -> str:
        text = ('Run a one-off isolated sub-agent (AgentDefinition '
                'by subagent_type, default general-purpose): spawns a '
                'fresh agent, runs synchronously, returns its final '
                'answer, then is reclaimed. Not a teammate.')
        lines = [f'- {agent_type}: {when_to_use}'
                 for agent_type, when_to_use in self.agent_defs.describe()]
        if lines:
            text += '\nAvailable subagent types:\n' + '\n'.join(lines)
        return text

    def tool_schemas(self) -> list[dict]:
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
                                                      'a one-off sub-agent.'}},
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
            ]
        return team_tools + [{'name': t.name, 'description': t.description,
                              'input_schema': t.parameters or {}}
                             for t in self._injected_tools]

    async def execute_tool(self, name: str, input: dict, agent: Agent,
                           tool_use_id: str = '') -> str:
        if agent is not None and not agent.hookless:
            pre = await self.hooks.execute_pre_tool_hooks(
                agent, tool_use_id, name, input)
            if pre.blocking_error is not None:
                return (f'Error: hook blocked tool "{name}": '
                        f'{pre.blocking_error.blocking_error}')
            if pre.updated_input is not None:
                input = {**input, **pre.updated_input}
        fn = {'send_message': _tools.send_message,
              'create_agent': _tools.create_agent,
              'task_stop': _tools.task_stop}.get(name)
        if fn is None:
            tool = next((t for t in self._injected_tools if t.name == name),
                        None)
            if tool is None:
                return f'Error: unknown tool "{name}"'
            try:
                out = tool(**input)
                if inspect.iscoroutine(out):
                    out = await out
                out = out if isinstance(out, str) else str(out)
            except Exception as e:
                if agent is not None and not agent.hookless:
                    await self.hooks.execute_post_tool_failure_hooks(
                        agent, tool_use_id, name, input, e)
                return f'Error calling tool "{name}": {type(e).__name__}: {e}'
            if agent is not None and not agent.hookless:
                await self.hooks.execute_post_tool_hooks(
                    agent, tool_use_id, name, input, out)
            return out
        try:
            out = await fn(self, agent, input)
        except Exception as e:
            if agent is not None and not agent.hookless:
                await self.hooks.execute_post_tool_failure_hooks(
                    agent, tool_use_id, name, input, e)
            return f'Error calling tool "{name}": {type(e).__name__}: {e}'
        if agent is not None and not agent.hookless:
            await self.hooks.execute_post_tool_hooks(
                agent, tool_use_id, name, input, out)
        return out

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
