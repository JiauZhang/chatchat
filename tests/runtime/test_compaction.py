"""A compaction that keeps failing must stop spending requests on itself until
the next turn, while a manual /compact stays available."""

import asyncio

from helpers import mock_team

WINDOW = 8_000
RESERVE = 2_000


def _conversation(turns=12):
    """Long enough for the compactor to have a middle worth summarizing."""
    messages = [{"role": "user", "content": "hi"}]
    messages += [{"role": "assistant", "content": "a"} for _ in range(turns - 2)]
    messages.append({"role": "assistant", "content": "a", "usage": {"prompt_tokens": 7_000, "completion_tokens": 50}})
    return messages


def _team(summarize, calls):
    def record(messages):
        calls.append(len(messages))
        return summarize(messages)

    team = mock_team("cmp", lambda m, t=None, stream_cb=None: "ok", context_window=WINDOW, compact_reserve=RESERVE)
    team.compactor.summarize = record
    return team


def _attempt(summarize, times=1, messages=None):
    """Runs the auto path over the same conversation `times` in a row."""
    calls = []

    async def main():
        team = _team(summarize, calls)
        kept = None
        for _ in range(times):
            kept = await team.compactor.maybe_compact(messages or _conversation(), agent=team.lead)
        return team, kept

    team, kept = asyncio.run(main())
    return team, calls, kept


def test_a_summarizer_that_raises_counts_as_one_failure():
    def broken(messages):
        raise RuntimeError("the model refused")

    team, calls, kept = _attempt(broken)
    assert calls == [2]
    assert team.lead.compact_failures == 1
    assert len(kept) == 12


def test_a_summarizer_that_returns_nothing_counts_as_one_failure():
    team, calls, kept = _attempt(lambda messages: None)
    assert calls == [2]
    assert team.lead.compact_failures == 1
    assert len(kept) == 12


def test_the_auto_path_stops_trying_after_three_failures():
    team, calls, kept = _attempt(lambda messages: None, times=5)
    assert calls == [2, 2, 2]
    assert team.lead.compact_failures == 3


def test_a_manual_compact_is_not_blocked_by_the_breaker():
    calls = []

    async def main():
        team = _team(lambda messages: None, calls)
        for _ in range(4):
            await team.compactor.maybe_compact(_conversation(), agent=team.lead)
        assert calls == [2, 2, 2]
        await team.compactor.maybe_compact(_conversation(), force=True, agent=team.lead)
        return calls

    assert asyncio.run(main()) == [2, 2, 2, 2]


def test_a_conversation_too_short_to_compress_spends_no_request():
    """The compactor keeps a head and a tail; with nothing between them there is
    nothing to summarize, and that is not a failure."""
    team, calls, kept = _attempt(lambda messages: messages, messages=_conversation(turns=9))
    assert calls == []
    assert team.lead.compact_failures == 0
    assert len(kept) == 9


def test_a_useful_compaction_clears_the_failures():
    async def main():
        team = _team(lambda messages: None, [])
        await team.compactor.maybe_compact(_conversation(), agent=team.lead)
        await team.compactor.maybe_compact(_conversation(), agent=team.lead)
        assert team.lead.compact_failures == 2
        team.compactor.summarize = lambda messages: "the story so far"
        return await team.compactor.maybe_compact(_conversation(), agent=team.lead), team

    kept, team = asyncio.run(main())
    assert team.lead.compact_failures == 0
    assert len(kept) < 12


def test_the_next_turn_tries_again():
    calls = []

    async def main():
        team = _team(lambda messages: None, calls)
        for _ in range(3):
            await team.compactor.maybe_compact(_conversation(), agent=team.lead)
        assert calls == [2, 2, 2]
        team.lead._begin_turn()
        await team.compactor.maybe_compact(_conversation(), agent=team.lead)

    asyncio.run(main())
    assert len(calls) == 4


def test_a_subagent_compacts_its_own_context(tmp_path):
    """Subagents used to be exempt from compaction entirely (internal=True), so
    a long research task grew unbounded until the provider rejected it."""

    async def main():
        team = mock_team("subcompact")
        team.define_agent("reader", system_prompt="read stuff")
        calls = []

        async def fake_compact(messages, force=False, agent=None):
            calls.append((agent.name if agent is not None else None, agent._internal if agent is not None else None))
            return messages

        team.compactor.maybe_compact = fake_compact
        await team.spawn_subagent("go", subagent_type="reader")
        return calls

    calls = asyncio.run(main())
    assert len(calls) == 1
    name, internal = calls[0]
    assert internal is True
    assert "reader" not in name
