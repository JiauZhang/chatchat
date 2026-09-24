"""A compaction that keeps failing must stop spending requests on itself until
the next turn, while a manual /compact stays available."""
import asyncio

from helpers import mock_team

WINDOW = 8_000
RESERVE = 2_000


def _full():
    return [{'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 7_000, 'completion_tokens': 50}}]


def _team(fallback, calls):
    def compact(messages):
        calls.append(len(messages))
        return fallback(messages)

    team = mock_team('cmp', lambda m, t=None, stream_cb=None: 'ok',
                     context_window=WINDOW, compact_reserve=RESERVE)
    team._compact_fn = compact
    return team


def _attempt(fallback, times=1):
    """Runs the auto path over the same conversation `times` in a row."""
    calls = []

    async def main():
        team = _team(fallback, calls)
        kept = None
        for _ in range(times):
            kept = await team.maybe_compact(_full(), agent=team.lead)
        return team, kept

    team, kept = asyncio.run(main())
    return team, calls, kept


def test_a_compaction_that_raises_counts_as_one_failure():
    def broken(messages):
        raise RuntimeError('the model refused')

    team, calls, kept = _attempt(broken)
    assert calls == [2]
    assert team.lead.compact_failures == 1
    assert len(kept) == 2


def test_a_compaction_that_returns_nothing_counts_as_one_failure():
    team, calls, kept = _attempt(lambda messages: None)
    assert team.lead.compact_failures == 1
    assert len(kept) == 2


def test_the_auto_path_stops_trying_after_three_failures():
    team, calls, kept = _attempt(lambda messages: None, times=5)
    assert calls == [2, 2, 2]
    assert team.lead.compact_failures == 3


def test_a_manual_compact_is_not_blocked_by_the_breaker():
    calls = []

    async def main():
        team = _team(lambda messages: None, calls)
        for _ in range(4):
            await team.maybe_compact(_full(), agent=team.lead)
        assert calls == [2, 2, 2]
        await team.compact(_full(), force=True)
        return calls

    assert asyncio.run(main()) == [2, 2, 2, 2]


def test_a_conversation_the_compactor_left_alone_is_not_a_failure():
    team, calls, kept = _attempt(lambda messages: messages)
    assert calls == [2]
    assert team.lead.compact_failures == 0
    assert kept is not None


def test_a_useful_compaction_clears_the_failures():
    async def main():
        team = _team(lambda messages: None, [])
        await team.maybe_compact(_full(), agent=team.lead)
        await team.maybe_compact(_full(), agent=team.lead)
        assert team.lead.compact_failures == 2
        team._compact_fn = lambda messages: messages[:1]
        return await team.maybe_compact(_full(), agent=team.lead), team

    kept, team = asyncio.run(main())
    assert team.lead.compact_failures == 0
    assert len(kept) == 1


def test_the_next_turn_tries_again():
    calls = []

    async def main():
        team = _team(lambda messages: None, calls)
        for _ in range(3):
            await team.maybe_compact(_full(), agent=team.lead)
        assert calls == [2, 2, 2]
        team.lead._begin_turn()
        await team.maybe_compact(_full(), agent=team.lead)

    asyncio.run(main())
    assert len(calls) == 4
