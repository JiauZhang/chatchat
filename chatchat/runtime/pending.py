"""Knowing when an agent has finished what it was given.

An agent is given work - a prompt, a message from a teammate, something that
arrived while it was busy - and a caller may want to wait until the work it
asked for is done.

Three things are kept apart here, because they answer different questions.
How much was given is a count of what arrived. How much was finished is a
count of what the agent has done with it. Whether the agent is free right
now is a signal - it says something happened, not that enough of it
happened. A caller waiting takes the count it cares about as its target and
is woken by the signal; it stops waiting when the count has been reached.
"""

import asyncio


class PendingWork:
    """What an agent has been given, what it has finished, and when it is free."""

    def __init__(self):
        self._given = 0
        self._finished = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def given(self):
        """Something was handed to the agent."""
        self._given += 1

    def finished(self):
        """The agent finished a piece of work."""
        self._finished += 1

    def take(self):
        """The agent is busy with it now, so it is not free."""
        self._idle.clear()

    def idle(self):
        """The agent is free; something happened that a waiter may want to
        hear about."""
        self._idle.set()

    def given_count(self) -> int:
        return self._given

    def finished_count(self) -> int:
        return self._finished

    def outstanding(self) -> int:
        return max(0, self._given - self._finished)

    def settled(self) -> bool:
        return self.outstanding() == 0

    async def wait(self, timeout: float | None = None):
        """Wait until the work given so far has been finished.

        The target is the count taken now: work handed over after this is not
        waited for, because the caller asked about this much of it.
        """
        target = self._given
        while self._finished < target:
            self._idle.clear()
            await asyncio.wait_for(self._idle.wait(), timeout)
