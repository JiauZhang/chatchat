from __future__ import annotations

import asyncio
import inspect

from chatchat.hooks.events import AGENT_COMPACT, emit
from chatchat.runtime.tokens import context_estimate

SUMMARY_MARK = "[conversation summary]"
MAX_COMPACT_FAILURES = 3

KEEP_RECENT = 8
HEAD_MESSAGES = 2


def summary_of(messages: list[dict]) -> str:
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content.startswith(SUMMARY_MARK):
            return content[len(SUMMARY_MARK) :].strip()
    return ""


def _note(agent, *, failed: bool) -> None:
    if agent is None:
        return
    agent.compact_failures = agent.compact_failures + 1 if failed else 0


class Compactor:
    """When and how a conversation is shortened.

    It is given everything it needs - how to summarize, the hooks to run around
    it, the window it must stay inside, and what to do once the conversation
    has shrunk - so it never reaches back for the team that owns it.
    """

    def __init__(self, *, summarize, hooks, window: int, reserve: int, on_compacted=None):
        self.summarize = summarize
        self.hooks = hooks
        self.window = int(window or 0)
        self.threshold = max(0, self.window - int(reserve))
        self.on_compacted = on_compacted

    @property
    def automatic(self) -> bool:
        return self.summarize is not None and self.window > 0

    def needed(self, messages: list[dict]) -> bool:
        return self.automatic and context_estimate(messages) >= self.threshold

    async def summarize_middle(self, messages: list[dict]) -> list[dict] | None:
        if len(messages) <= KEEP_RECENT + HEAD_MESSAGES:
            return messages
        head = messages[:HEAD_MESSAGES]
        tail = messages[-KEEP_RECENT:]
        middle = messages[HEAD_MESSAGES:-KEEP_RECENT]
        text = self.summarize(middle)
        if inspect.isawaitable(text):
            text = await text
        if not isinstance(text, str) or not text.strip():
            return None
        return head + [{"role": "user", "content": f"{SUMMARY_MARK}\n{text}"}] + tail

    async def maybe_compact(self, messages: list[dict], force: bool = False, agent=None) -> list[dict]:
        failures = getattr(agent, "compact_failures", 0)
        if not force and agent is not None and failures >= MAX_COMPACT_FAILURES:
            return messages
        if not force and not self.needed(messages):
            return messages
        trigger = "manual" if force else "auto"
        await self.hooks.execute_pre_compact_hooks(trigger=trigger)
        try:
            result = self.summarize_middle(messages)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception:
            _note(agent, failed=True)
            return messages
        if result is None:
            _note(agent, failed=True)
            return messages
        if len(result) >= len(messages):
            return list(result) if result else messages
        _note(agent, failed=False)
        if self.on_compacted is not None:
            self.on_compacted()
        emit(
            AGENT_COMPACT,
            agent="",
            before=len(messages),
            after=len(result),
            summarized=len(messages) - len(result) + 1,
            summary=summary_of(result),
        )
        await self.hooks.execute_post_compact_hooks(trigger=trigger)
        return list(result)
