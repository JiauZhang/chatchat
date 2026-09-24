from __future__ import annotations

import asyncio
import logging
import time

from chatchat.client import Usage
from chatchat.core.abort import Abort, AbortSignal
from chatchat.core.context import spawn_task
from chatchat.core.inbox_poller import InboxPoller
from chatchat.core.mailbox import Mailbox, parse_protocol
from chatchat.core.metrics import Metrics
from chatchat.core.task import Task, generate_task_id
from chatchat.core.tasks import work_prompt
from chatchat.hooks.output import describe_blocking
from chatchat.tool import describe_tools
from chatchat.hooks.events import (AGENT_PROGRESS, AGENT_REASON_START,
                                   AGENT_TEXT, AGENT_TOOL_CALL,
                                   AGENT_TURN_FINISHED, AGENT_WARN, emit)

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, agent_id, name, team, client, ctx, *,
                 instruction: str = '',
                 internal: bool = False, hookless: bool = False,
                 depth: int = 0,
                 tools: list | None = None,
                 model_timeout: float = 120.0,
                 model_retries: int = 2,
                 on_message=None,
                 inbox=None,
                 agent_type: str = ''):
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
        self.agent_type = agent_type
        self.tools = tools
        self.model_timeout = model_timeout
        self.model_retries = model_retries

        self.total_usage = Usage()
        self.metrics = Metrics()
        self.last_metrics = Metrics()
        self.total_metrics = Metrics()
        self.compact_failures = 0
        self._turn_open = False
        self.inbox = inbox if inbox is not None else Mailbox()
        self.messages: list[dict] = []
        self.busy = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.poller = InboxPoller(
            self.inbox, self._queue,
            handlers={'shutdown_request': self._on_shutdown_request},
            on_enqueue=self._bump_pending,
            task_feed=None if internal or ctx.leader else self._next_task,
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
        self.on_message = on_message
        self.task: Task | None = None

    @property
    def tool_context(self):
        return self.team.tool_context

    def _record(self, message: dict):
        if self.on_message is not None:
            self.on_message(message)

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
            self._end_turn()
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
            self._emit_state()
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
                logger.exception('agent %s failed a turn: %s', self.name, e)
                if not self._internal:
                    await self.team.hooks.execute_stop_failure_hooks(self, e)
            finally:
                self._end_turn()
                self.busy = False
                if self._internal:
                    self._done += 1
                self._set_idle()
            self._emit_state()
            if not self._internal:
                stop_res = await self.team.hooks.execute_stop_hooks(
                    self, stop_hook_active=self._stop_hook_active)
                if stop_res.blocking_error is not None:
                    self._stop_hook_active = True
                    self._queue.put_nowait(describe_blocking(
                        stop_res.blocking_error))
                    continue
                self._stop_hook_active = False
                if not stop_res.continue_loop:
                    if stop_res.stop_reason:
                        emit(AGENT_WARN, agent=self.name,
                             text=stop_res.stop_reason)
                    self._stop.set()
                if not self.ctx.leader:
                    idle_res = await self.team.hooks.execute_teammate_idle_hooks(
                        self)
                    if idle_res.blocking_error is not None:
                        self._queue.put_nowait(describe_blocking(
                            idle_res.blocking_error))
                        continue
                await self.team.notify_idle(self, reason=reason,
                                            failure_reason=error or None)
            self._done += 1
            self._set_idle()

    def tool_schemas(self, context) -> list[dict]:
        if self.tools is None:
            return self.team.tool_schemas(context)
        return describe_tools(self.tools, context)

    def _emit_progress(self, msg: dict, usage: dict | None = None):
        if not self._internal:
            return
        data = {'message': msg}
        if usage is not None:
            data['usage'] = usage
        emit(AGENT_PROGRESS, agent=self.name, **data)

    def _begin_turn(self) -> None:
        self._turn_open = True
        self.metrics = Metrics()
        self.compact_failures = 0

    def _end_turn(self) -> None:
        if not self._turn_open:
            return
        self._turn_open = False
        self.last_metrics = self.metrics
        self.total_metrics += self.metrics

    async def _full_turn(self, user_block: str) -> str:
        self._begin_turn()
        self._work_abort = AbortSignal()
        if user_block:
            self.messages.append({'role': 'user', 'content': user_block})
        if not self.hookless and not self._instructions_loaded:
            self._instructions_loaded = True
            for item in self.team.instruction_files:
                await self.team.hooks.execute_instructions_loaded_hooks(
                    self, item.get('path', ''), item.get('memory_type', ''),
                    load_reason=item.get('load_reason', 'session_start'))
        if not self.hookless and user_block:
            pre = await self.team.hooks.execute_user_prompt_submit_hooks(
                self, user_block)
            if pre.blocking_error is not None:
                if self.messages and self.messages[-1].get('role') == 'user' \
                        and self.messages[-1].get('content') == user_block:
                    self.messages.pop()
                text = describe_blocking(pre.blocking_error)
                emit(AGENT_WARN, agent=self.name, text=text)
                emit(AGENT_TURN_FINISHED, agent=self.name)
                return text
            if pre.additional_context:
                self.messages[-1] = {
                    'role': 'user',
                    'content': f'{user_block}\n\n{pre.additional_context}'}

        if user_block:
            self._record(self.messages[-1])

        await self.poll_inbox()

        if not self._internal:
            self.messages = await self.team.maybe_compact(self.messages,
                                                          agent=self)

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
                stream_state['text_emitted'] = True
                emit(AGENT_TEXT, agent=self.name, delta=text)

        self.ctx.abort.check()
        self._work_abort.check()
        while True:
            self.ctx.abort.check()
            self._work_abort.check()
            attachment = self._drain_attachments()
            if attachment:
                msg = {'role': 'user', 'content': attachment}
                self.messages.append(msg)
                self._record(msg)
            attempt = 0
            while True:
                self.ctx.abort.check()
                self._work_abort.check()
                thinking_parts.clear()
                stream_state['text_emitted'] = False
                round_started = time.monotonic()
                respond_task = asyncio.create_task(self.client.respond(
                    self.messages, self.tool_schemas(
                    self.tool_context), stream_cb=stream))
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
                if resp is not None:
                    break
                attempt += 1
                if stream_state['text_emitted'] or attempt > self.model_retries:
                    msg = f'Error: model call timed out after {self.model_timeout}s'
                    logger.warning('agent %s: %s', self.name, msg)
                    emit(AGENT_WARN, agent=self.name, text=msg)
                    emit(AGENT_TURN_FINISHED, agent=self.name)
                    return ''
                emit(AGENT_WARN, agent=self.name, text=(
                    f'model call timed out after {self.model_timeout}s, '
                    f'retrying ({attempt}/{self.model_retries})'))
            self.metrics.api_round(int((time.monotonic()
                                        - round_started) * 1000))
            self.total_usage.add(getattr(self.client, '_last_usage', None))
            if isinstance(resp, str):
                msg = {'role': 'assistant', 'content': resp,
                       'usage': self.client._last_usage.to_dict()}
                if thinking_parts:
                    msg['thinking'] = ''.join(thinking_parts)
                self._emit_progress(msg, usage=self.client._last_usage.to_dict())
                self.messages.append(msg)
                self._record(msg)
                emit(AGENT_TURN_FINISHED, agent=self.name)
                return resp
            assistant_msg = {'role': 'assistant',
                             'content': [tu_todict(t) for t in resp],
                             'usage': self.client._last_usage.to_dict()}
            if thinking_parts:
                assistant_msg['thinking'] = ''.join(thinking_parts)
            self._emit_progress(assistant_msg,
                                usage=self.client._last_usage.to_dict())
            self.messages.append(assistant_msg)
            self._record(assistant_msg)
            results = []
            for tu in resp:
                emit(AGENT_TOOL_CALL, agent=self.name, tool=tu.name,
                     input=tu.input, tool_use_id=tu.id)
                self._in_tool = tu.name
                try:
                    outcome = await self.team.execute_tool(
                        tu.name, tu.input, self, tu.id)
                finally:
                    self._in_tool = None
                results.append({'type': 'tool_result',
                                'tool_use_id': tu.id, 'content': outcome.text})
                if outcome.additional_context:
                    results.append({'type': 'text',
                                    'text': outcome.additional_context})
            self._emit_progress({'role': 'user', 'content': results})
            results_msg = {'role': 'user', 'content': results}
            self.messages.append(results_msg)
            self._record(results_msg)

    async def poll_inbox(self):
        text = await self.poller.poll_once()
        if text is not None:
            self._bump_pending()
            self._queue.put_nowait(text)

    async def _next_task(self) -> str | None:
        tasks = self.team.tasks
        if tasks is None or self.busy:
            return None
        task = tasks.available()
        if task is None or not tasks.claim(task.id, self.name).ok:
            return None
        tasks.update(task.id, status='in_progress')
        return work_prompt(task)

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
