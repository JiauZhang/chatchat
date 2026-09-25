"""Standing system-prompt rules: every agent client carries the injection
warning the reference puts in its core system section, and utility calls
(compaction) stay clean of it."""
from chatchat.team.standing import STANDING_INSTRUCTION, with_standing


def test_every_agent_instruction_ends_with_the_injection_warning():
    assert with_standing('You are the lead.').endswith(STANDING_INSTRUCTION)
    assert with_standing('') == STANDING_INSTRUCTION


def test_the_warning_is_appended_once_and_keeps_the_original_text():
    assert with_standing('Be brief.') == 'Be brief.\n\n' + STANDING_INSTRUCTION
    assert with_standing(with_standing('x')).count('outside') == 1


def test_the_standing_text_warns_about_planted_instructions():
    assert 'outside' in STANDING_INSTRUCTION
    assert 'user' in STANDING_INSTRUCTION
