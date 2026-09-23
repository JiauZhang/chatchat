"""A print-mode run with a required shape must end with a payload that fits it."""
import asyncio

from helpers import mock_team

TOOL = 'structured_output'

SCHEMA = {'type': 'object',
          'properties': {'name': {'type': 'string'},
                         'score': {'type': 'number'}},
          'required': ['name']}


def _send(name, payload, schema=SCHEMA):
    async def main():
        team = mock_team(name)
        assert team.set_output_schema(schema) == ''
        return team, await team.execute_tool(TOOL, payload, team.lead)

    return asyncio.run(main())


def test_the_requested_shape_is_offered_as_a_tool():
    async def main():
        team = mock_team('shape1')
        before = [schema['name'] for schema in
                  team.tool_schemas(team.tool_context)]
        team.set_output_schema(SCHEMA)
        schemas = {schema['name']: schema
                   for schema in team.tool_schemas(team.tool_context)}
        return before, schemas

    before, schemas = asyncio.run(main())
    assert TOOL not in before
    assert schemas[TOOL]['input_schema'] == SCHEMA


def test_a_schema_that_is_not_a_schema_is_refused():
    async def main():
        team = mock_team('shape2')
        problem = team.set_output_schema({'type': 'not-a-type'})
        names = [schema['name'] for schema in
                 team.tool_schemas(team.tool_context)]
        return problem, names

    problem, names = asyncio.run(main())
    assert 'not-a-type' in problem
    assert TOOL not in names


def test_a_payload_that_fits_is_kept_for_the_caller():
    team, outcome = _send('shape3', {'name': 'round', 'score': 0.5})
    assert outcome.text.startswith('Error') is False
    assert team.structured_output == {'name': 'round', 'score': 0.5}


def test_a_payload_that_does_not_fit_is_sent_back_with_the_offence():
    team, outcome = _send('shape4', {'name': 'round', 'score': 'high'})
    assert outcome.text.startswith('Error:')
    assert 'score' in outcome.text
    assert team.structured_output is None

    team, missing = _send('shape5', {'score': 1})
    assert missing.text.startswith('Error:')
    assert 'name' in missing.text


def test_the_run_cannot_stop_while_the_payload_is_missing():
    async def main():
        team = mock_team('shape6')
        team.set_output_schema(SCHEMA)
        blocked = (await team.hooks.execute_stop_hooks(team.lead))
        await team.execute_tool(TOOL, {'name': 'round'}, team.lead)
        return blocked, await team.hooks.execute_stop_hooks(team.lead)

    blocked, after = asyncio.run(main())
    assert blocked.blocking_error is not None
    assert TOOL in blocked.blocking_error.blocking_error
    assert after.blocking_error is None


def test_enforcement_gives_up_rather_than_looping_forever(monkeypatch):
    monkeypatch.setenv('MAX_STRUCTURED_OUTPUT_RETRIES', '2')

    async def main():
        team = mock_team('shape7')
        team.set_output_schema(SCHEMA)
        return [await team.hooks.execute_stop_hooks(team.lead)
                for _ in range(3)]

    first, second, third = asyncio.run(main())
    assert first.blocking_error is not None
    assert second.blocking_error is not None
    assert third.blocking_error is None
