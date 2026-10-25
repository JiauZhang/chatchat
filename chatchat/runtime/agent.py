from __future__ import annotations

import asyncio
import logging

from chatchat.client import Usage
from chatchat.runtime.abort import Abort, AbortSignal
from chatchat.runtime.context import spawn_task
from chatchat.team.inbox_poller import InboxPoller
from chatchat.team.mailbox import Mailbox, parse_protocol, shutdown_approved
from chatchat.runtime.metrics import Metrics
from chatchat.runtime.model_caller import ModelCaller
from chatchat.runtime.pending import PendingWork
from chatchat.runtime.turn import Turn, _Blocked, blocked_text
from chatchat.runtime.skills import listing_budget
from chatchat.tasks.task import Task, generate_task_id
from chatchat.tasks.tasks import work_prompt
from chatchat.hooks.output import describe_blocking
from chatchat.runtime.tool_runner import ToolRunner
from chatchat.tool import describe_tools
from chatchat.hooks.events import (
    AGENT_PROGRESS,
    AGENT_WARN,
    emit,
)

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        agent_id,
        name,
        team,
        client,
        ctx,
        *,
        instruction: str = "",
        internal: bool = False,
        hookless: bool = False,
        depth: int = 0,
        tools: list | None = None,
        model_timeout: float = 120.0,
        model_retries: int = 2,
        max_turns: int | None = None,
        tool_context=None,
        on_message=None,
        inbox=None,
        agent_type: str = "",
    ):
        self.agent_id = agent_id
        self.name = name
        self.team = team
        self._client = client
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
        self.max_turns = max_turns
        self._tool_context = tool_context

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
            self.inbox,
            self._queue,
            handlers={"shutdown_request": self._on_shutdown_request},
            on_enqueue=self._bump_pending,
            task_feed=None if internal or ctx.leader else self._next_task,
        )
        self._loop_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.work = PendingWork()
        self._attachments: list[str] = []
        self._skill_listing_seen = -1
        self._stop_hook_active = False
        self.work_abort = AbortSignal()
        self._in_tool: str | None = None
        self.on_message = on_message
        self.task: Task | None = None
        self.caller = ModelCaller(self._client, timeout=model_timeout, retries=model_retries, agent_name=name)
        self.tools_runner = ToolRunner(execute=self._run_tool, agent_name=name)

    @property
    def client(self):
        """The client this agent talks to the model through.

        Changing the model or the thinking level gives the lead a new client;
        the caller that asks the model has to be given it too, or it would
        keep asking through the old one while the answer is read from the
        new one.
        """
        return self._client

    @client.setter
    def client(self, client):
        self._client = client
        if hasattr(self, "caller"):
            self.caller.client = client

    @property
    def tool_context(self):
        return self._tool_context if self._tool_context is not None else self.team.tool_context

    def _record(self, message: dict):
        if self.on_message is not None:
            self.on_message(message)

    def start(self):
        if self._loop_task is not None and not self._loop_task.done():
            return
        self.poller.start()
        if self.task is None:
            self.task = Task(
                id=generate_task_id("in_process_teammate"),
                type="in_process_teammate",
                agent_id=self.agent_id,
                abort=self.ctx.abort,
            )
            self.task.status = "running"
        self._loop_task = spawn_task(self.ctx, self._run(), name=self.agent_id)

    def abort_work(self):
        self.work_abort.abort()

    def interrupt_and_submit(self, text: str, *, cancelable_tools: tuple = ()):
        if self._in_tool and self._in_tool in cancelable_tools:
            self.work_abort.abort()
        self.submit(text)

    def _finalize(self, status: str):
        if self.task is not None:
            self.task.set_terminal(status)

    async def stop(self, *, status: str = "killed"):
        self._stop.set()
        self.ctx.abort.abort()
        self.work_abort.abort()
        self._queue.put_nowait("")
        await self.poller.stop()
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        self._loop_task = None
        self._finalize(status)

    @property
    def is_running(self) -> bool:
        return (
            self._loop_task is not None
            and not self._loop_task.done()
            and self.poller._task is not None
            and not self.poller._task.done()
        )

    def submit(self, text: str):
        self.work.given()
        self.work.take()
        self._queue.put_nowait(text)

    def enqueue_attachment(self, text: str):
        self._attachments.append(text)
        if not self.busy and self._queue.empty() and self.work.settled():
            self.work.given()
            self.work.take()
            self._queue.put_nowait("")

    def wake_from_hook(self, text: str):
        """The model is woken with what a hook had to say.

        A hook that blocked is the model being told to do something else, so
        the next turn is a turn that a hook asked for: the hook knows it is
        already inside one.
        """
        self._stop_hook_active = True
        self.enqueue_attachment(text)

    def _drain_attachments(self):
        if not self._attachments:
            return ""
        text = "\n\n".join(self._attachments)
        self._attachments.clear()
        return text

    def _queue_skill_listing(self) -> None:
        """The skill listing rides a system-reminder attachment instead of the
        Skill tool's description: a mutating description busts the tools cache
        (claude-code measured 10.2% of fleet cache_creation tokens on exactly
        that), and this is also how a conditionally activated skill becomes
        visible the moment it activates."""
        skills = getattr(self.team, "skills", None)
        if skills is None:
            return
        version = getattr(skills, "listing_version", 0)
        if version == self._skill_listing_seen:
            return
        self._skill_listing_seen = version
        listing = skills.listing(listing_budget(self.team.context_window))
        if listing:
            self._attachments.append(f"<system-reminder>\nAvailable skills:\n{listing}\n</system-reminder>")

    async def chat(self, text: str) -> str:
        self.busy = True
        try:
            return await self._full_turn(text)
        finally:
            self._end_turn()
            self.busy = False
            self.work.finished()
            self.work.idle()

    async def idle(self) -> bool:
        return not self.busy and self._queue.empty() and not self.inbox.unread()

    async def wait_idle(self, timeout: float | None = None):
        await self.work.wait(timeout)

    def last_assistant(self, *, start: int = 0) -> str:
        for message in reversed(self.messages[start:]):
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant" and isinstance(message.get("content"), str):
                return message["content"]
        for message in reversed(self.messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                    return block["content"]
        return ""

    async def _run(self):
        while not self._stop.is_set():
            self.ctx.abort.check()
            block = await self._queue.get()
            if self._stop.is_set():
                break
            self.busy = True
            self._emit_state()
            reason = "available"
            error = ""
            try:
                await self._full_turn(block)
            except Abort:
                reason = "interrupted"
            except asyncio.CancelledError:
                break
            except Exception as e:
                reason = "failed"
                error = str(e)
                logger.exception("agent %s failed a turn: %s", self.name, e)
                if not self._internal:
                    await self.team.hooks.execute_stop_failure_hooks(self, e)
            finally:
                self._end_turn()
                self.busy = False
            self._emit_state()
            if not self._internal:
                stop_res = await self.team.hooks.execute_stop_hooks(self, stop_hook_active=self._stop_hook_active)
                if stop_res.blocking_error is not None:
                    self._stop_hook_active = True
                    self._queue.put_nowait(describe_blocking(stop_res.blocking_error))
                    self.work.idle()
                    continue
                self._stop_hook_active = False
                if not stop_res.continue_loop:
                    if stop_res.stop_reason:
                        emit(AGENT_WARN, agent=self.name, text=stop_res.stop_reason)
                    self._stop.set()
                if not self.ctx.leader:
                    idle_res = await self.team.hooks.execute_teammate_idle_hooks(self)
                    if idle_res.blocking_error is not None:
                        self._queue.put_nowait(describe_blocking(idle_res.blocking_error))
                        self.work.idle()
                        continue
                await self.team.notify_idle(self, reason=reason, failure_reason=error or None)
            self.work.finished()
            self.work.idle()

    async def _run_tool(self, call):
        self._in_tool = call.name
        try:
            return await self.team.execute_tool(call.name, call.input, self, call.id)
        finally:
            self._in_tool = None

    def tool_schemas(self, context) -> list[dict]:
        if self.tools is None:
            return self.team.tool_schemas(context)
        return describe_tools(self.tools, context)

    def _emit_progress(self, msg: dict, usage: dict | None = None):
        if not self._internal:
            return
        data = {"message": msg}
        if usage is not None:
            data["usage"] = usage
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
        self.work_abort = AbortSignal()
        turn = Turn(
            agent=self,
            messages=self.messages,
            tools=self.tools,
            max_turns=self.max_turns,
            hookless=self.hookless,
        )
        try:
            return await turn.run(user_block)
        except _Blocked as blocked:
            return blocked_text(blocked)
        finally:
            self.messages = turn.messages

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
        tasks.update(task.id, status="in_progress")
        return work_prompt(task)

    def _bump_pending(self):
        self.work.given()

    def _on_shutdown_request(self, m):
        req = parse_protocol(m.text) or {}
        self.team.send_control(m.from_, shutdown_approved(req.get("request_id", ""), self.name))
        self.team.request_shutdown(self.agent_id)

    def _emit_state(self):
        emit("agent.state", agent=self.name, busy=self.busy, queue=self._queue.qsize(), unread=len(self.inbox.unread()))


def is_attachment_message(message) -> bool:
    """Attachment injections (the skill listing, background-task notices) ride
    the context as user messages — claude-code builds the same sequence,
    [userMessage, ...attachmentMessages] — but they are system injections, not
    conversation turns. claude-code renders the initial skill listing as null
    and keeps invisible attachments out of its message count (CC-724); hosts
    counting turns apply the same rule through this predicate."""
    return isinstance(message, dict) and message.get("attachment") is True


def tu_todict(tu) -> dict:
    return {"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input}
