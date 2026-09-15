from __future__ import annotations

import asyncio

from chatchat.client import Usage
from chatchat.core.abort import Abort, AbortSignal
from chatchat.core.context import spawn_task
from chatchat.core.inbox_poller import InboxPoller
from chatchat.core.mailbox import Mailbox, parse_protocol
from chatchat.core.task import Task, generate_task_id
from chatchat.hooks.events import (AGENT_PROGRESS, AGENT_REASON_START,
                                   AGENT_TEXT, AGENT_TOOL_CALL,
                                   AGENT_TURN_FINISHED, AGENT_WARN, emit)


class Agent:
    def __init__(self, agent_id, name, team, client, ctx, *,
                 instruction: str = '',
                 internal: bool = False, hookless: bool = False,
                 depth: int = 0,
                 tool_exec=None, model_timeout: float = 120.0,
                 inbox=None):
        self.agent_id = agent_id
        self.name = name
        self.team = team
        self.client = client
        self.ctx = ctx
        self.instruction = instruction
        self._internal = internal
        self.hookless = hookless
        self._instructions_loaded = False
        self.depth = depth
        self.model_timeout = model_timeout
        self.tool_exec = tool_exec if tool_exec is not None else team

        self.total_usage = Usage()
        self.inbox = inbox if inbox is not None else Mailbox()
        self.messages: list[dict] = []
        self.busy = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.poller = InboxPoller(
            self.inbox, self._queue,
            handlers={'shutdown_request': self._on_shutdown_request},
            on_enqueue=self._bump_pending,
        )
        self._loop_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._idle_event = asyncio.Event()
        self._pending = 0
        self._done = 0
        self._attachments: list[str] = []
        self._stop_hook_active = False
        self._work_abort = AbortSignal()
        self._in_tool: str | None = None
        self.task: Task | None = None

    def start(self):
        if self._loop_task is not None and not self._loop_task.done():
            return
        self.poller.start()
        if self.task is None:
            self.task = Task(id=generate_task_id('in_process_teammate'),
                             type='in_process_teammate',
                             agent_id=self.agent_id,
                             abort=self.ctx.abort)
            self.task.status = 'running'
        self._loop_task = spawn_task(self.ctx, self._run(),
                                     name=self.agent_id)

    def abort_work(self):
        self._work_abort.abort()

    def interrupt_and_submit(self, text: str, *, cancelable_tools: tuple = ()):
        if self._in_tool and self._in_tool in cancelable_tools:
            self._work_abort.abort()
        self.submit(text)

    def _finalize(self, status: str):
        if self.task is not None:
            self.task.set_terminal(status)

    async def stop(self, *, status: str = 'killed'):
        self._stop.set()
        self.ctx.abort.abort()
        self._work_abort.abort()
        self._queue.put_nowait('')
        await self.poller.stop()
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        self._loop_task = None
        self._set_idle()
        self._finalize(status)

    @property
    def is_running(self) -> bool:
        return (self._loop_task is not None and not self._loop_task.done()
                and self.poller._task is not None and not self.poller._task.done())

    def submit(self, text: str):
        self._pending += 1
        self._clear_idle()
        self._queue.put_nowait(text)

    def enqueue_attachment(self, text: str):
        self._attachments.append(text)
        if not self.busy and self._queue.empty() and self._pending == self._done:
            self._pending += 1
            self._clear_idle()
            self._queue.put_nowait('')

    def _drain_attachments(self):
        if not self._attachments:
            return ''
        text = '\n\n'.join(self._attachments)
        self._attachments.clear()
        return text

    async def chat(self, text: str) -> str:
        self._clear_idle()
        self.busy = True
        try:
            return await self._full_turn(text)
        finally:
            self.busy = False
            self._set_idle()

    async def idle(self) -> bool:
        return (not self.busy and self._queue.empty()
                and not self.inbox.unread())

    def _clear_idle(self):
        self._idle_event.clear()

    def _set_idle(self):
        self._idle_event.set()

    async def wait_idle(self, timeout: float | None = None):
        target = self._pending
        while self._done < target:
            self._idle_event.clear()
            await asyncio.wait_for(self._idle_event.wait(), timeout)

    async def _run(self):
        while not self._stop.is_set():
            self.ctx.abort.check()
            block = await self._queue.get()
            if self._stop.is_set():
                break
            self._clear_idle()
            self.busy = True
            reason = 'available'
            error = ''
            try:
                await self._full_turn(block)
            except Abort:
                reason = 'interrupted'
            except asyncio.CancelledError:
                break
            except Exception as e:
                reason = 'failed'
                error = str(e)
                if not self._internal:
                    await self.team.hooks.execute_stop_failure_hooks(self, e)
            finally:
                self.busy = False
                if self._internal:
                    self._done += 1
                self._set_idle()
            self._emit_state()
            if not self._internal:
                stop_res = await self.team.hooks.execute_stop_hooks(
                    self, stop_hook_active=self._stop_hook_active)
                if stop_res.blocking_error is not None:
                    from chatchat.hooks.output import get_stop_hook_message
                    self._stop_hook_active = True
                    self._queue.put_nowait(get_stop_hook_message(
                        stop_res.blocking_error))
                    continue
                self._stop_hook_active = False
                if not self.ctx.leader:
                    await self.team.hooks.execute_teammate_idle_hooks(self)
                await self.team.notify_idle(self, reason=reason,
                                            failure_reason=error or None)
            self._done += 1
            self._set_idle()

    def _emit_progress(self, msg: dict, usage: dict | None = None):
        if not self._internal:
            return
        data = {'message': msg}
        if usage is not None:
            data['usage'] = usage
        emit(AGENT_PROGRESS, agent=self.name, **data)

    async def _full_turn(self, user_block: str) -> str:
        self._work_abort = AbortSignal()
        if user_block:
            self.messages.append({'role': 'user', 'content': user_block})
        if not self.hookless and not self._instructions_loaded:
            self._instructions_loaded = True
            for item in self.team.instruction_files:
                await self.team.hooks.execute_instructions_loaded_hooks(
                    self, item.get('content', ''),
                    load_reason=item.get('load_reason', 'init'),
                    path=item.get('path', ''))
        if not self.hookless and user_block:
            pre = await self.team.hooks.execute_user_prompt_submit_hooks(
                self, user_block)
            if pre.blocking_error is not None:
                from chatchat.hooks.output import (
                    get_user_prompt_submit_hook_blocking_message)
                if self.messages and self.messages[-1].get('role') == 'user' \
                        and self.messages[-1].get('content') == user_block:
                    self.messages.pop()
                text = get_user_prompt_submit_hook_blocking_message(
                    pre.blocking_error)
                emit(AGENT_WARN, agent=self.name, text=text)
                emit(AGENT_TURN_FINISHED, agent=self.name)
                return text
            if pre.additional_context:
                self.messages[-1] = {
                    'role': 'user',
                    'content': f'{user_block}\n\n{pre.additional_context}'}

        await self.poll_inbox()

        if not self._internal:
            self.messages = await self.team.maybe_compact(self.messages)

        stream_state = {'reason_emitted': False}
        thinking_parts = []

        def stream(text, kind):
            if kind == 'warn':
                emit(AGENT_WARN, agent=self.name, text=text)
            elif kind == 'reason':
                if not stream_state['reason_emitted']:
                    emit(AGENT_REASON_START, agent=self.name)
                    stream_state['reason_emitted'] = True
                thinking_parts.append(text)
            elif kind == 'text':
                emit(AGENT_TEXT, agent=self.name, delta=text)

        self.ctx.abort.check()
        self._work_abort.check()
        while True:
            self.ctx.abort.check()
            self._work_abort.check()
            attachment = self._drain_attachments()
            if attachment:
                self.messages.append({'role': 'user', 'content': attachment})
            thinking_parts.clear()
            respond_task = asyncio.create_task(self.client.respond(
                self.messages, self.tool_exec.tool_schemas(), stream_cb=stream))
            abort_waiter = asyncio.create_task(self._work_abort.wait())
            resp = None
            try:
                await asyncio.wait_for(
                    asyncio.wait({respond_task, abort_waiter},
                                 return_when=asyncio.FIRST_COMPLETED),
                    timeout=self.model_timeout)
                if self._work_abort.aborted:
                    self._work_abort.check()
                resp = await respond_task
            except asyncio.TimeoutError:
                pass
            finally:
                if not abort_waiter.done():
                    abort_waiter.cancel()
                if not respond_task.done():
                    respond_task.cancel()
                    try:
                        await respond_task
                    except (asyncio.CancelledError, Exception):
                        pass
            if resp is None:
                msg = f'Error: model call timed out after {self.model_timeout}s'
                emit(AGENT_WARN, agent=self.name, text=msg)
                emit(AGENT_TURN_FINISHED, agent=self.name)
                return ''
            self.total_usage.add(getattr(self.client, '_last_usage', None))
            if isinstance(resp, str):
                msg = {'role': 'assistant', 'content': resp}
                if thinking_parts:
                    msg['thinking'] = ''.join(thinking_parts)
                self._emit_progress(msg, usage=self.client._last_usage.to_dict())
                self.messages.append(msg)
                emit(AGENT_TURN_FINISHED, agent=self.name)
                return resp
            assistant_msg = {'role': 'assistant',
                              'content': [tu_todict(t) for t in resp]}
            if thinking_parts:
                assistant_msg['thinking'] = ''.join(thinking_parts)
            self._emit_progress(assistant_msg,
                                usage=self.client._last_usage.to_dict())
            self.messages.append(assistant_msg)
            results = []
            for tu in resp:
                emit(AGENT_TOOL_CALL, agent=self.name, tool=tu.name,
                     input=tu.input, tool_use_id=tu.id)
                self._in_tool = tu.name
                try:
                    out = await self.tool_exec.execute_tool(tu.name, tu.input,
                                                            self, tu.id)
                finally:
                    self._in_tool = None
                results.append({'type': 'tool_result',
                                'tool_use_id': tu.id, 'content': out})
            self._emit_progress({'role': 'user', 'content': results})
            self.messages.append({'role': 'user', 'content': results})

    async def poll_inbox(self):
        text = await self.poller.poll_once()
        if text is not None:
            self._bump_pending()
            self._queue.put_nowait(text)

    def _bump_pending(self):
        self._pending += 1

    def _on_shutdown_request(self, m):
        from chatchat.core.mailbox import shutdown_approved
        req = parse_protocol(m.text) or {}
        self.team.send_control(m.from_, shutdown_approved(
            req.get('request_id', ''), self.name))
        self.team.request_shutdown(self.agent_id)

    def _emit_state(self):
        emit('agent.state', agent=self.name,
             busy=self.busy, queue=self._queue.qsize(),
             unread=len(self.inbox.unread()))


def tu_todict(tu) -> dict:
    return {'type': 'tool_use', 'id': tu.id, 'name': tu.name,
            'input': tu.input}
