"""The loop that goes back and forth between the model and its tools.

A turn is not one exchange. The model answers, asks for tools, gets their
answers, and often asks for more; the loop is what keeps that going until
the model has nothing left to ask for. The turn limit and the skill listing
and the attachments that arrived meanwhile all live here, because they are
what decides whether another round happens.

The loop is separate from the agent so that it can be read on its own: what
the model was told, what it said, what its tools answered, and when the
whole thing is over.
"""

from chatchat.hooks.output import describe_blocking
from chatchat.hooks.events import (
    AGENT_REASON_START,
    AGENT_TEXT,
    AGENT_TURN_FINISHED,
    AGENT_WARN,
    emit,
)
from chatchat.runtime.skills import listing_budget


class Turn:
    """One turn of an agent's conversation."""

    def __init__(
        self,
        *,
        agent,
        client,
        messages: list[dict],
        tools,
        max_turns: int | None = None,
        hookless: bool = False,
    ):
        self.agent = agent
        self.client = client
        self.messages = messages
        self.tools = tools
        self.max_turns = max_turns
        self.hookless = hookless
        self.thinking_parts: list[str] = []
        self.rounds = 0
        self._reason_emitted = False
        self._text_emitted = False
        self._skill_listing_seen = -1

    async def run(self, user_block: str) -> str:
        """The agent's answer, or what it was told instead of one."""
        if user_block:
            self.messages.append({"role": "user", "content": user_block})
        await self._load_instructions()
        await self._submit_prompt(user_block)
        await self.agent.poll_inbox()
        await self._compact()
        return await self._loop()

    async def _load_instructions(self):
        if self.hookless or self.agent._instructions_loaded:
            return
        self.agent._instructions_loaded = True
        for item in self.agent.team.instruction_files:
            await self.agent.team.hooks.execute_instructions_loaded_hooks(
                self.agent,
                item.get("path", ""),
                item.get("memory_type", ""),
                load_reason=item.get("load_reason", "session_start"),
            )

    async def _submit_prompt(self, user_block: str):
        """What the person said goes to the model, unless a hook says no."""
        if self.hookless or not user_block:
            return
        pre = await self.agent.team.hooks.execute_user_prompt_submit_hooks(self.agent, user_block)
        if pre.blocking_error is not None:
            if self.messages and self.messages[-1].get("role") == "user" and self.messages[-1].get("content") == user_block:
                self.messages.pop()
            text = describe_blocking(pre.blocking_error)
            emit(AGENT_WARN, agent=self.agent.name, text=text)
            emit(AGENT_TURN_FINISHED, agent=self.agent.name)
            raise _Blocked(text)
        if pre.additional_context:
            self.messages[-1] = {"role": "user", "content": f"{user_block}\n\n{pre.additional_context}"}
        self.agent._record(self.messages[-1])

    async def _compact(self):
        before = len(self.messages)
        self.messages = await self.agent.team.compactor.maybe_compact(self.messages, agent=self.agent)
        if len(self.messages) < before:
            self._skill_listing_seen = -1

    async def _loop(self) -> str:
        while True:
            self.agent.ctx.abort.check()
            self.agent.work_abort.check()
            self.rounds += 1
            if self.max_turns is not None and self.rounds > self.max_turns:
                note = f"Stopped: the turn limit ({self.max_turns}) was reached."
                emit(AGENT_WARN, agent=self.agent.name, text=note)
                emit(AGENT_TURN_FINISHED, agent=self.agent.name)
                return note
            self._queue_skill_listing()
            await self._drain_attachments()
            answer = await self._ask()
            if answer is None:
                return await self._timed_out()
            if isinstance(answer, str):
                return await self._finished(answer)
            await self._run_tools(answer)

    async def _ask(self):
        """The model's answer, or None when it kept timing out."""
        self.thinking_parts.clear()
        self._text_emitted = False
        answer, elapsed_ms = await self.agent.caller.ask(
            self.messages,
            self.agent.tool_schemas(self.agent.tool_context),
            abort=self.agent.work_abort,
            stream=self._stream,
            spoke=lambda: self._text_emitted,
        )
        self.agent.metrics.api_round(elapsed_ms)
        if answer is not None:
            self.agent.total_usage.add(getattr(self.client, "_last_usage", None))
        return answer

    async def _timed_out(self) -> str:
        msg = f"Error: model call timed out after {self.agent.model_timeout}s"
        emit(AGENT_WARN, agent=self.agent.name, text=msg)
        emit(AGENT_TURN_FINISHED, agent=self.agent.name)
        return ""

    async def _finished(self, answer: str) -> str:
        message = {
            "role": "assistant",
            "content": answer,
            "model": getattr(self.client, "model", "") or "",
            "usage": self.client._last_usage.to_dict(),
        }
        if self.thinking_parts:
            message["thinking"] = "".join(self.thinking_parts)
        items = getattr(self.client, "_last_response_items", None)
        if items:
            message["response_items"] = items
        self.agent._emit_progress(message, usage=self.client._last_usage.to_dict())
        self.messages.append(message)
        self.agent._record(message)
        emit(AGENT_TURN_FINISHED, agent=self.agent.name)
        return answer

    async def _run_tools(self, calls):
        outcomes = await self.agent.tools_runner.run(calls)
        self.agent._emit_progress({"role": "user", "content": [o.as_result() for o in outcomes]})
        message = self.agent.tools_runner.as_message(outcomes)
        self.messages.append(message)
        self.agent._record(message)

    def _stream(self, text, kind):
        if kind == "warn":
            emit(AGENT_WARN, agent=self.agent.name, text=text)
        elif kind == "reason":
            if not self._reason_emitted:
                emit(AGENT_REASON_START, agent=self.agent.name)
                self._reason_emitted = True
            self.thinking_parts.append(text)
        elif kind == "text":
            self._text_emitted = True
            emit(AGENT_TEXT, agent=self.agent.name, delta=text)

    def _queue_skill_listing(self) -> None:
        """The skill listing rides a system-reminder attachment instead of the
        Skill tool's description: a mutating description busts the tools cache
        (claude-code measured 10.2% of fleet cache_creation tokens on exactly
        that), and this is also how a conditionally activated skill becomes
        visible the moment it activates."""
        skills = getattr(self.agent.team, "skills", None)
        if skills is None:
            return
        version = getattr(skills, "listing_version", 0)
        if version == self._skill_listing_seen:
            return
        self._skill_listing_seen = version
        listing = skills.listing(listing_budget(self.agent.team.context_window))
        if listing:
            self.agent._attachments.append(f"<system-reminder>\nAvailable skills:\n{listing}\n</system-reminder>")

    async def _drain_attachments(self):
        """What arrived while the model was thinking goes in before the next
        question."""
        if not self.agent._attachments:
            return
        text = "\n\n".join(self.agent._attachments)
        self.agent._attachments.clear()
        message = {"role": "user", "content": text, "attachment": True}
        self.messages.append(message)
        self.agent._record(message)


class _Blocked(Exception):
    """A hook refused the prompt; what it said is the answer."""


def is_blocked(error: Exception) -> bool:
    return isinstance(error, _Blocked)


def blocked_text(error: Exception) -> str:
    return str(error)
