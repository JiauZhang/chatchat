from __future__ import annotations

import asyncio
from pathlib import Path

from chatchat.runtime.filehistory import FileHistory


class Conversation:
    """What the team has been told, and what it has said back.

    The lead holds the messages, but the conversation is more than that list:
    a turn may be running, a session may need its hooks fired, and a
    checkpoint may have to be taken before the files change. The conversation
    holds that, so the team is left with the agents and the tools.
    """

    def __init__(self, *, lead, hooks, tool_context=None, history: FileHistory | None = None):
        self.lead = lead
        self.hooks = hooks
        self.tool_context = tool_context
        self.history = history
        self.started = False
        self.source = "startup"
        self.setup_done = False

    def transcript(self) -> list[dict]:
        return list(self.lead.messages)

    def restore(self, messages: list[dict]) -> None:
        self.lead.messages = [m for m in messages if isinstance(m, dict)]
        if self.lead.messages:
            self.source = "resume"

    def begin_new_session(self, source: str = "clear") -> None:
        self.source = source
        self.started = False

    async def end_session(self, reason: str) -> None:
        await self.hooks.execute_session_end_hooks(reason)

    async def open_session(self) -> None:
        aggs = []
        if not self.setup_done:
            self.setup_done = True
            aggs.append(await self.hooks.execute_setup_hooks())
        aggs.append(await self.hooks.execute_session_start_hooks(self.source))
        for agg in aggs:
            if agg.additional_context:
                self.lead.messages.append({"role": "user", "content": agg.additional_context})

    async def query(self, prompt: str, timeout: float | None = None) -> str:
        if not self.started:
            self.started = True
            await self.open_session()
        if self.history is not None:
            self.history.snapshot(len(self.lead.messages))
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

    def turns(self) -> list[tuple[int, str]]:
        if self.history is None:
            return []
        marks = {snap.mark for snap in self.history.snapshots}
        return [
            (index, str(message.get("content") or ""))
            for index, message in enumerate(self.lead.messages)
            if index in marks and message.get("role") == "user"
        ]

    def rewind(self, mark: int, *, code: bool = True, conversation: bool = True) -> dict:
        files = self.history.rewind(mark) if code and self.history is not None else []
        removed = 0
        if conversation:
            kept = self.lead.messages[: int(mark)]
            removed = len(self.lead.messages) - len(kept)
            self.lead.messages = list(kept)
        return {"files": files, "messages": removed}

    def use_file_history(self, directory, cwd=None) -> FileHistory:
        """Point the snapshot store at a directory, dropping what was read
        from the previous one."""
        cwd = cwd or (self.tool_context.cwd if self.tool_context is not None else Path.cwd())
        self.history = FileHistory(Path(directory), cwd=cwd)
        if self.tool_context is not None:
            self.tool_context.files = self.history
        return self.history
