import asyncio
import time

from chatchat.runtime.abort import AbortSignal
from chatchat.runtime.agent import Agent
from chatchat.runtime.context import AgentContext
from chatchat.team.sidechain import SidechainWriter
from chatchat.tasks.task import rand_name
from chatchat.hooks.events import AGENT_PROGRESS, emit


def _tool_calls(agent: Agent) -> int:
    return sum(1 for message in agent.messages
               if isinstance(message.get('content'), list)
               for block in message['content']
               if isinstance(block, dict) and block.get('type') == 'tool_use')


class SubagentsMixin:
    async def _start_subagent(self, prompt: str, subagent_type: str | None,
                              instruction: str, model, depth: int,
                              fork_msgs: list | None, tool_use_id: str):
        defn = self.agent_defs.get(subagent_type)
        sys_prompt = '\n'.join(p for p in (defn.full_prompt(), instruction)
                               if p) or defn.system_prompt
        if defn.memory and self.agent_memory is not None:
            sys_prompt = '\n\n'.join(
                (sys_prompt,
                 self.agent_memory.prompt(defn.agent_type, defn.memory)))
        name = rand_name(f'sub-{self._counter}')
        self._counter += 1
        agent_id = self.agent_id(name)
        abort = AbortSignal()
        ctx = AgentContext(agent_id=agent_id, agent_name=name,
                           team_name=self.name, abort=abort, leader=False)
        writer = None
        if self.sidechain_dir is not None:
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
