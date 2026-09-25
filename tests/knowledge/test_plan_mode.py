"""Plan mode: the model asks to design first, and the plan needs approval."""
import asyncio

from chatchat.knowledge.plan import APPROVE, AUTO_ACCEPT, KEEP_PLANNING
from helpers import mock_team


def _team(name, tmp_path):
    team = mock_team(name)
    team.plan_path = tmp_path / 'plan.md'
    team.ask_user = lambda agent, questions: []
    return team


def test_entering_plan_mode_switches_the_session(tmp_path):
    async def main():
        team = _team('plan1', tmp_path)
        outcome = await team.execute_tool('EnterPlanMode', {}, team.lead)
        return outcome.text, team.hooks.permission_mode

    text, mode = asyncio.run(main())
    assert mode == 'plan'
    assert str(tmp_path / 'plan.md') in text


def test_entering_twice_is_a_no_op(tmp_path):
    async def main():
        team = _team('plan2', tmp_path)
        await team.execute_tool('EnterPlanMode', {}, team.lead)

        class _Gate:
            def __init__(self):
                self.modes = []

            def __call__(self, mode):
                self.modes.append(mode)

        gate = _Gate()
        team._plan_mode_changed = gate
        outcome = await team.execute_tool('EnterPlanMode', {}, team.lead)
        return outcome.text, gate.modes

    text, modes = asyncio.run(main())
    assert 'Already in plan mode' in text
    assert modes == []


def test_a_plan_that_was_never_written_cannot_be_approved(tmp_path):
    async def main():
        team = _team('plan3', tmp_path)
        team.ask_user = lambda agent, questions: [APPROVE]
        return await team.execute_tool('ExitPlanMode', {}, team.lead)

    outcome = asyncio.run(main())
    assert outcome.text.startswith('Error:')
    assert 'plan.md' in outcome.text


def test_approving_the_plan_leaves_plan_mode_with_the_plan(tmp_path):
    async def main():
        team = _team('plan4', tmp_path)
        (tmp_path / 'plan.md').write_text('1. rename the parser\n')
        team.hooks.permission_mode = 'plan'
        modes = []
        team._plan_mode_changed = modes.append
        team.ask_user = lambda agent, questions: [APPROVE]
        outcome = await team.execute_tool('ExitPlanMode', {}, team.lead)
        return outcome.text, modes, team.ask_user

    text, modes, _asker = asyncio.run(main())
    assert modes == ['default']
    assert 'rename the parser' in text
    assert 'approved' in text


def test_asking_for_auto_accept_answers_with_that_mode(tmp_path):
    async def main():
        team = _team('plan5', tmp_path)
        (tmp_path / 'plan.md').write_text('the plan\n')
        team.hooks.permission_mode = 'plan'
        modes = []
        team._plan_mode_changed = modes.append
        team.ask_user = lambda agent, questions: [AUTO_ACCEPT]
        outcome = await team.execute_tool('ExitPlanMode', {}, team.lead)
        return outcome.text, modes

    text, modes = asyncio.run(main())
    assert modes == ['acceptEdits']
    assert 'the plan' in text


def test_keeping_planning_leaves_the_session_in_plan_mode(tmp_path):
    async def main():
        team = _team('plan6', tmp_path)
        (tmp_path / 'plan.md').write_text('the plan\n')
        team.hooks.permission_mode = 'plan'
        modes = []
        team._plan_mode_changed = modes.append
        team.ask_user = lambda agent, questions: [KEEP_PLANNING]
        outcome = await team.execute_tool('ExitPlanMode', {}, team.lead)
        return outcome.text, modes

    text, modes = asyncio.run(main())
    assert modes == []
    assert 'did not approve' in text


def test_the_plan_question_offers_the_three_ways_out(tmp_path):
    async def main():
        team = _team('plan7', tmp_path)
        (tmp_path / 'plan.md').write_text('the plan\n')
        team.hooks.permission_mode = 'plan'
        asked = []

        def asker(agent, questions):
            asked.extend(questions)
            return [APPROVE]

        team.ask_user = asker
        await team.execute_tool('ExitPlanMode', {}, team.lead)
        return asked

    asked = asyncio.run(main())
    labels = [option['label'] for option in asked[0]['options']]
    assert labels == [APPROVE, AUTO_ACCEPT, KEEP_PLANNING]
