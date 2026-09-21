import asyncio

from chatchat.client import Usage
from helpers import mock_team

_USAGE = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
          'prompt_tokens_details': {'cached_tokens': 80}}


def test_usage_from_dict_and_add():
    a = Usage.from_dict({'prompt_tokens': 285, 'completion_tokens': 55,
                         'total_tokens': 340,
                         'prompt_tokens_details': {'cached_tokens': 256}})
    b = Usage.from_dict({'prompt_tokens': 10, 'completion_tokens': 20,
                         'total_tokens': 30,
                         'prompt_tokens_details': {'cached_tokens': 5}})
    a.add(b)
    assert a.prompt_tokens == 295
    assert a.completion_tokens == 75
    assert a.total_tokens == 370
    assert a.prompt_tokens_details == {'cached_tokens': 261}


def test_usage_from_dict_none_keeps_zeros():
    u = Usage.from_dict(None)
    assert u.prompt_tokens == 0
    assert u.completion_tokens == 0
    assert u.total_tokens == 0
    assert u.prompt_tokens_details is None


def test_team_query_accumulates_usage():
    async def main():
        team = mock_team('u', usage=_USAGE)
        await team.query('hi')
        await team.query('again')
        return team.usage()

    usage = asyncio.run(main())
    assert usage.prompt_tokens == 200
    assert usage.completion_tokens == 40
    assert usage.total_tokens == 240
    assert usage.prompt_tokens_details['cached_tokens'] == 160


def test_team_last_usage_is_one_response_not_the_session_total():
    async def main():
        team = mock_team('one', usage=_USAGE)
        await team.query('hi')
        await team.query('again')
        return team.last_usage(), team.usage()

    last, total = asyncio.run(main())
    assert (last.prompt_tokens, last.completion_tokens,
            last.total_tokens) == (100, 20, 120)
    assert total.total_tokens == 240


def test_team_last_usage_survives_a_request_that_has_not_answered():
    """A client clears its own counter when a request starts, so a reading taken
    mid-request is nothing: the window is measured against the last response
    that actually came back."""
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = []

    async def respond(messages, tools=None, *, stream_cb=None):
        calls.append(messages)
        if len(calls) > 1:
            started.set()
            await finish.wait()
        return 'ok'

    async def main():
        team = mock_team('in-flight', handler=respond, usage=_USAGE)
        await team.query('hi')
        turn = asyncio.create_task(team.query('again'))
        await started.wait()
        usage = team.last_usage()
        finish.set()
        await turn
        return usage

    usage = asyncio.run(main())
    assert (usage.prompt_tokens, usage.completion_tokens,
            usage.total_tokens) == (100, 20, 120)
    assert usage.prompt_tokens_details == {'cached_tokens': 80}


def test_team_last_usage_is_none_before_any_response():
    async def main():
        return mock_team('fresh').last_usage()

    assert asyncio.run(main()) is None


def test_team_usage_adds_up_what_the_subagents_spent():
    """A sub-agent's tokens were spent on this session, so the session total has
    to include them; `last_usage` stays the lead's because it measures the
    context window the lead is actually filling."""
    async def main():
        team = mock_team('sub', usage=_USAGE)
        await team.query('hi')
        await team.spawn_subagent('go')
        return team.usage(), team.last_usage()

    total, last = asyncio.run(main())
    assert (total.prompt_tokens, total.completion_tokens) == (200, 40)
    assert total.total_tokens == 240
    assert total.prompt_tokens_details['cached_tokens'] == 160
    assert last.total_tokens == 120


def test_resetting_usage_clears_the_whole_team():
    async def main():
        team = mock_team('sub', usage=_USAGE)
        await team.query('hi')
        await team.spawn_subagent('go')
        team.reset_usage()
        return team.usage()

    assert asyncio.run(main()).total_tokens == 0


def test_team_last_usage_is_zero_for_a_client_that_never_reports():
    async def main():
        team = mock_team('z')
        await team.query('hi')
        return team.last_usage()

    assert asyncio.run(main()).total_tokens == 0


def test_provider_without_usage_keeps_zeros():
    async def main():
        team = mock_team('silent')
        await team.query('hi')
        return team.usage()

    usage = asyncio.run(main())
    assert usage.total_tokens == 0
    assert usage.prompt_tokens_details is None
