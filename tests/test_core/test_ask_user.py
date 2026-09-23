"""A question the model asks has to reach a human and come back as answers."""
import asyncio

from helpers import mock_team


def _question(header='shape', **kw):
    return dict({'question': 'Which shape?', 'header': header,
                 'options': [{'label': 'round', 'description': 'a circle'},
                             {'label': 'square'}]}, **kw)


def _ask(name, questions, asker=None, seen=None):
    async def main():
        team = mock_team(name)
        if asker is not None:
            team.ask_user = asker
        if seen is not None:
            team.hooks.register(
                'Elicitation', '*',
                fn=lambda inp: seen.append(('ask', inp.get('message'))) or True)
            team.hooks.register(
                'ElicitationResult', '*',
                fn=lambda inp: seen.append(('result', inp.get('response'))))
        return await team.execute_tool('ask_user', {'questions': questions},
                                       team.lead)

    return asyncio.run(main())


def test_the_answers_come_back_with_the_question():
    outcome = _ask('ask1', [_question()], asker=lambda agent, questions: ['round'])
    assert 'Which shape?' in outcome.text
    assert 'round' in outcome.text


def test_the_asker_sees_every_question_it_is_asked():
    asked = []

    def answer(agent, questions):
        asked.append(questions)
        return ['round, square']

    outcome = _ask('ask2', [_question(), _question(multiSelect=True)],
                   asker=answer)
    assert asked[0][1]['multiSelect'] is True
    assert 'round, square' in outcome.text


def test_both_ends_of_the_round_trip_are_reported_to_hooks():
    seen = []
    _ask('ask3', [_question()],
         asker=lambda agent, questions: ['round'], seen=seen)
    assert ('ask', 'Which shape?') in seen
    assert ('result', 'Which shape?: round') in seen


def test_a_question_is_unreachable_when_no_one_can_answer_it():
    outcome = _ask('ask4', [_question()])
    assert 'not available to this agent' in outcome.text


def test_malformed_questions_are_refused_before_anyone_is_bothered():
    asked = []
    bad = ([],
           [{'options': [{'label': 'x'}, {'label': 'y'}]}, _question()],
           [_question(options=[{'label': 'only one'}])])
    for questions in bad:
        outcome = _ask('ask5', questions,
                       asker=lambda agent, q: asked.append(q) or ['x'])
        assert outcome.text.startswith('Error:'), questions
    assert asked == []


def test_a_header_stays_short_enough_to_be_a_tab():
    outcome = _ask('ask6', [_question('a-header-too-long-for-the-tab')],
                   asker=lambda agent, questions: ['round'])
    assert outcome.text.startswith('Error:') and 'header' in outcome.text


def test_the_question_tool_is_offered_only_when_someone_can_answer():
    async def main():
        team = mock_team('ask7')
        before = [schema['name'] for schema in
                  team.tool_schemas(team.tool_context)]
        team.ask_user = lambda agent, questions: []
        after = [schema['name'] for schema in team.tool_schemas(
            team.tool_context)]
        return before, after

    before, after = asyncio.run(main())
    assert 'ask_user' not in before
    assert 'ask_user' in after
