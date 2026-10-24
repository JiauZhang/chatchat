"""What a team has spent, and who keeps the numbers."""

import asyncio

from helpers import mock_team

from chatchat.runtime.metrics import Metrics


def _team():
    return mock_team("led", tasks_dir=None)


def test_last_usage_is_none_before_the_model_has_answered():
    async def main():
        return _team().ledger.last_usage()

    assert asyncio.run(main()) is None


def test_last_usage_reads_the_most_recent_message_that_reported_one():
    async def main():
        team = _team()
        team.lead.messages = [
            {"role": "assistant", "content": "a", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "b", "usage": {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42}},
        ]
        return team.ledger.last_usage().total_tokens

    assert asyncio.run(main()) == 42


def test_usage_sums_every_agent_that_spent_anything():
    async def main():
        team = _team()
        team.lead.total_usage = type(team.lead.total_usage)(prompt_tokens=100, completion_tokens=10, total_tokens=110)
        worker = team.create_agent("worker")
        worker.total_usage = type(worker.total_usage)(prompt_tokens=50, completion_tokens=5, total_tokens=55)
        return team.ledger.usage().total_tokens

    assert asyncio.run(main()) == 165


def test_reset_zeroes_every_agent():
    async def main():
        team = _team()
        worker = team.create_agent("worker")
        team.lead.total_usage = type(team.lead.total_usage)(prompt_tokens=100, completion_tokens=10, total_tokens=110)
        worker.total_usage = type(worker.total_usage)(prompt_tokens=50, completion_tokens=5, total_tokens=55)
        team.ledger.reset()
        return team.ledger.usage().total_tokens, team.lead.metrics.tool_calls

    total, tool_calls = asyncio.run(main())
    assert total == 0
    assert tool_calls == 0


def test_restore_seeds_the_per_turn_fields_too():
    async def main():
        team = _team()
        team.ledger.restore({"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}, {"tool_calls": 7})
        return (
            team.lead.total_usage.total_tokens,
            team.lead.last_metrics.tool_calls,
            team.lead.total_metrics.tool_calls,
        )

    total, last, running = asyncio.run(main())
    assert total == 1000
    assert last == 7
    assert running == 7


def test_context_tokens_reads_the_occupancy_the_provider_reported():
    async def main():
        team = _team()
        team.lead.messages = [
            {"role": "assistant", "content": "a", "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320}}
        ]
        return team.ledger.context_tokens()

    assert asyncio.run(main()) == 320


def test_total_metrics_adds_the_agents_up():
    async def main():
        team = _team()
        worker = team.create_agent("worker")
        team.lead.total_metrics = Metrics(tool_calls=2)
        worker.total_metrics = Metrics(tool_calls=3)
        return team.ledger.total_metrics().tool_calls

    assert asyncio.run(main()) == 5
