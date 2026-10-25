import asyncio
import time

from chatchat.client import MockClient
from chatchat.team.team import Team


async def _team():
    """A team whose lead is not already running: the hook is fired by hand,
    not by a turn ending."""
    team = Team("demo", MockClient())
    await team.lead.stop()
    return team


def test_a_background_hook_that_blocked_wakes_the_model():
    """A hook that ran on its own and blocked has something the model has to
    answer, so the model is woken up with it."""

    async def main():
        team = await _team()
        lead = team.lead
        team.hooks.register(
            "Stop",
            command="echo 'not ready' >&2; exit 2",
            async_rewake=True,
        )
        await team.hooks.execute_stop_hooks(lead)
        for _ in range(100):
            if lead._attachments:
                break
            await asyncio.sleep(0.02)
        return list(lead._attachments)

    attachments = asyncio.run(main())
    assert len(attachments) == 1
    assert attachments[0].startswith("<system-reminder>")
    assert "not ready" in attachments[0]
    assert attachments[0].endswith("</system-reminder>")


def test_a_background_hook_that_did_not_block_says_nothing():
    """A hook that ran and was happy has nothing to tell the model."""

    async def main():
        team = await _team()
        lead = team.lead
        team.hooks.register(
            "Stop",
            command="echo fine; exit 0",
            async_rewake=True,
        )
        await team.hooks.execute_stop_hooks(lead)
        await asyncio.sleep(0.3)
        return list(lead._attachments)

    assert asyncio.run(main()) == []


def test_a_hook_that_wakes_the_model_runs_in_the_background():
    """A hook that wakes the model says it implies running in the
    background, so the model is not held up waiting for it."""

    async def main():
        team = await _team()
        lead = team.lead
        team.hooks.register(
            "Stop",
            command="sleep 0.4; echo 'not ready' >&2; exit 2",
            async_rewake=True,
        )
        started = time.monotonic()
        await team.hooks.execute_stop_hooks(lead)
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.5)
        return elapsed

    assert asyncio.run(main()) < 1.0


def test_the_model_is_told_it_is_already_inside_a_hook():
    """The turn that a hook asked for says so, so the hook knows it is
    already inside one and does not ask again."""

    async def main():
        team = await _team()
        lead = team.lead
        seen = []

        def hook(inp):
            seen.append(bool(inp.get("stop_hook_active")))
            return True

        team.hooks.register("Stop", fn=hook)
        await team.hooks.execute_stop_hooks(lead)
        lead.wake_from_hook("<system-reminder>something</system-reminder>")
        await team.hooks.execute_stop_hooks(lead, stop_hook_active=lead._stop_hook_active)
        return seen

    assert asyncio.run(main()) == [False, True]
