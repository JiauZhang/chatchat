import asyncio

from chatchat.core.abort import AbortSignal
from chatchat.core.context import AgentContext, current_agent, spawn_task
from chatchat.core.team import token_count
from chatchat.core.tokens import context_estimate
from helpers import mock_team


def _make_ctx(name):
    return AgentContext(agent_id=f'{name}@team', agent_name=name, team_name='team',
                        abort=AbortSignal(), leader=(name == 'team-lead'))


def test_spawn_task_isolates_concurrent_contexts():
    async def main():
        seen = {}

        async def work(name):
            await asyncio.sleep(0.01 if name == 'x' else 0.02)
            seen[name] = current_agent().agent_name

        a = spawn_task(_make_ctx('x'), work('x'), name='x')
        b = spawn_task(_make_ctx('y'), work('y'), name='y')
        await asyncio.gather(a, b)
        assert seen == {'x': 'x', 'y': 'y'}

    asyncio.run(main())


def test_there_is_no_ambient_agent_outside_a_task():
    assert current_agent() is None


def test_context_size_anchors_on_the_last_measured_response():
    """The API's own count of the request it answered is the whole measurement;
    a message appended afterwards is not guessed at."""
    msgs = [{'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 900, 'completion_tokens': 100}},
            {'role': 'user', 'content': 'x' * 400}]
    assert token_count(msgs) == 900 + 100


def test_context_size_is_zero_until_the_api_has_measured_it():
    assert token_count([{'role': 'user', 'content': 'x' * 400}]) == 0


def test_an_older_response_does_not_replace_a_newer_one():
    msgs = [{'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 10, 'completion_tokens': 1}},
            {'role': 'user', 'content': 'more'},
            {'role': 'assistant', 'content': 'b',
             'usage': {'prompt_tokens': 50, 'completion_tokens': 5}}]
    assert token_count(msgs) == 55


def test_compaction_triggers_on_measured_context_near_the_window():
    async def summarize(messages, tools=None, *, stream_cb=None):
        return 'short'

    async def main():
        team = mock_team('ctx', handler=summarize,
                         context_window=8_000, compact_reserve=2_000)
        team.lead.messages = [
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 7_000, 'completion_tokens': 50}}]
        untouched = await team.maybe_compact(team.lead.messages)
        assert untouched is team.lead.messages or len(untouched) == 2
        team.lead.messages.append(
            {'role': 'assistant', 'content': 'b',
             'usage': {'prompt_tokens': 6_500, 'completion_tokens': 50}})
        return team, await team.maybe_compact(team.lead.messages)

    team, compacted = asyncio.run(main())
    assert team.compact_threshold == 6_000
    assert compacted is not team.lead.messages


def test_the_trigger_estimate_adds_a_rough_count_of_what_came_afterwards():
    msgs = [{'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 500, 'completion_tokens': 50}},
            {'role': 'user', 'content': 'x' * 400}]
    assert context_estimate(msgs) == 550 + 100


def test_the_estimate_guesses_until_the_api_has_measured_anything():
    assert context_estimate([]) == 0
    assert context_estimate([{'role': 'user', 'content': 'x' * 400},
                             {'role': 'assistant', 'content': 'y' * 400}]) == 200


def test_a_tool_call_is_counted_by_its_arguments():
    small = [{'role': 'assistant', 'content': [
        {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}}]}]
    big = [{'role': 'assistant', 'content': [
        {'type': 'tool_use', 'name': 'Read',
         'input': {'file_path': 'a' * 420}}]}]
    assert context_estimate(small) < context_estimate(big)
    assert context_estimate(big) - context_estimate(small) >= 100


def test_a_tool_result_is_counted_by_its_own_text():
    msgs = [{'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't1',
         'content': 'z' * 400}]}]
    assert context_estimate(msgs) == 100


def test_the_trigger_estimates_but_the_readout_keeps_the_measured_figure():
    async def summarize(messages, tools=None, *, stream_cb=None):
        return 'short'

    async def main():
        team = mock_team('ctx', handler=summarize, context_window=8_000,
                         compact_reserve=2_000)
        team.lead.messages = [
            {'role': 'assistant', 'content': 'a',
             'usage': {'prompt_tokens': 5_900, 'completion_tokens': 50}},
            {'role': 'user', 'content': 'x' * 400}]
        return team, await team.maybe_compact(team.lead.messages)

    team, compacted = asyncio.run(main())
    assert team.context_tokens == 5_950
    assert compacted is not team.lead.messages
