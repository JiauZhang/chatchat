"""A turn's cost is more than tokens: what it touched, how long it took, what it was refused."""
from unittest.mock import ANY

from chatchat.core.metrics import Metrics


def test_a_fresh_turn_reports_nothing_happened():
    metrics = Metrics()
    assert metrics.as_dict() == {'tool_calls': 0, 'tool_ms': 0,
                                 'lines_added': 0, 'lines_removed': 0,
                                 'api_ms': 0, 'requests': 0, 'hooks': 0,
                                 'hook_ms': 0, 'denials': 0}


def test_a_tool_call_adds_its_own_measured_time_and_its_diff():
    metrics = Metrics()
    metrics.tool_ran(1200, added=12, removed=3)
    metrics.tool_ran(300)
    assert metrics.tool_calls == 2
    assert metrics.tool_ms == 1500
    assert (metrics.lines_added, metrics.lines_removed) == (12, 3)


def test_a_model_round_trip_counts_separately_from_the_tools():
    metrics = Metrics()
    metrics.api_round(900)
    metrics.api_round(600)
    assert (metrics.requests, metrics.api_ms) == (2, 1500)


def test_a_hook_run_and_a_refusal_are_counted():
    metrics = Metrics()
    metrics.hook_ran(40)
    metrics.refused()
    metrics.refused()
    assert (metrics.hooks, metrics.hook_ms, metrics.denials) == (1, 40, 2)


def test_two_turns_add_up_without_editing_the_first():
    first = Metrics()
    first.tool_ran(1000, added=4)
    first.api_round(500)
    second = Metrics()
    second.tool_ran(250, removed=1)
    second.api_round(250)
    total = first + second
    assert total.tool_calls == 2
    assert total.tool_ms == 1250
    assert total.api_ms == 750
    assert (total.lines_added, total.lines_removed) == (4, 1)
    assert first.tool_ms == 1000


def test_zero_durations_are_recorded_as_they_are():
    metrics = Metrics()
    metrics.tool_ran(0)
    metrics.hook_ran(0)
    assert (metrics.tool_calls, metrics.tool_ms) == (1, 0)
    assert (metrics.hooks, metrics.hook_ms) == (1, 0)


from chatchat.tool import ToolResult, tool
from helpers import mock_team


@tool(name='Tee', description='write a file',
      parameters={'type': 'object', 'properties': {
          'path': {'type': 'string'}}, 'required': ['path']})
def tee(context, path):
    return ToolResult('written', {'num_added': 5, 'num_removed': 2})


def _instrumented_team(name):
    return mock_team(name, tools=[tee]), tee


def test_a_tool_call_is_measured_on_the_agent_that_made_it():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met1')
        await team.execute_tool('Tee', {'path': 'a.txt'}, team.lead)
        return team.lead.metrics

    metrics = asyncio.run(main())
    assert metrics.tool_calls == 1
    assert (metrics.lines_added, metrics.lines_removed) == (5, 2)
    assert metrics.tool_ms >= 0


def test_a_refused_call_is_counted_as_a_denial():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met2')
        team.hooks.register('PreToolUse', 'Tee', fn=lambda inp: False)
        outcome = await team.execute_tool('Tee', {'path': 'a.txt'}, team.lead)
        return outcome, team.lead.metrics

    outcome, metrics = asyncio.run(main())
    assert 'hook blocked' in outcome.text
    assert metrics.denials == 1
    assert metrics.tool_calls == 0


def test_hooks_that_run_for_a_call_are_counted():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met3')
        team.hooks.register('PostToolUse', 'Tee',
                            fn=lambda inp: True, timeout=5)
        await team.execute_tool('Tee', {'path': 'a.txt'}, team.lead)
        return team.lead.metrics

    metrics = asyncio.run(main())
    assert metrics.hooks >= 1
    assert metrics.hook_ms >= 0


def test_a_turn_is_measured_on_its_own_and_adds_into_the_agent_total():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met4')
        lead = team.lead
        lead._begin_turn()
        await team.execute_tool('Tee', {'path': 'a.txt'}, lead)
        lead.metrics.api_round(120)
        before = lead.total_metrics
        lead._end_turn()
        return lead, before

    lead, before = asyncio.run(main())
    assert (lead.last_metrics.tool_calls, lead.last_metrics.requests) == (1, 1)
    assert lead.last_metrics.api_ms == 120
    assert lead.total_metrics.tool_calls == before.tool_calls + 1
    assert lead.total_metrics.api_ms == 120
    assert lead.metrics.tool_calls == 1


def test_a_closed_turn_leaves_nothing_in_the_next_one():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met4b')
        lead = team.lead
        lead._begin_turn()
        await team.execute_tool('Tee', {'path': 'a.txt'}, lead)
        lead._end_turn()
        lead._begin_turn()
        return lead

    lead = asyncio.run(main())
    assert lead.metrics.as_dict() == Metrics().as_dict()
    assert lead.last_metrics.tool_calls == 1


def test_the_team_reads_back_the_last_turn_and_the_session_total():
    import asyncio

    async def main():
        team, _ = _instrumented_team('met5')
        team.lead._begin_turn()
        await team.execute_tool('Tee', {'path': 'a.txt'}, team.lead)
        team.lead._end_turn()
        worker = team.create_agent('worker', instruction='help')
        worker._begin_turn()
        await team.execute_tool('Tee', {'path': 'b.txt'}, worker)
        worker._end_turn()
        turn = team.turn_metrics()
        total = team.total_metrics()
        await team.stop_agent(worker)
        return turn, total

    turn, total = asyncio.run(main())
    assert turn.tool_calls == 1
    assert total.tool_calls == 2
    assert total.lines_added == 10


def test_clearing_the_session_clears_the_measured_totals_too():
    import asyncio

    async def respond(messages, tools=None, *, stream_cb=None):
        return 'done'

    async def main():
        team = mock_team('met6', handler=respond, tools=[tee])
        await team.execute_tool('Tee', {'path': 'a.txt'}, team.lead)
        team.lead.last_metrics = team.lead.metrics
        team.reset_usage()
        return team.total_metrics(), team.turn_metrics()

    total, turn = asyncio.run(main())
    assert total.tool_calls == 0
    assert turn.tool_calls == 0
