from chatchat.hooks.matchers import (if_condition_applies, if_matches,
                                     matches_pattern, parse_if_condition)


def test_wildcard():
    assert matches_pattern('Bash', '*')
    assert matches_pattern('Bash', '')
    assert matches_pattern('', '*')


def test_exact_and_alternation():
    assert matches_pattern('Bash', 'Bash')
    assert matches_pattern('Bash', 'Bash|Read')
    assert matches_pattern('Read', 'Bash|Read')
    assert not matches_pattern('Write', 'Bash|Read')


def test_regex():
    assert matches_pattern('Read', r'R.*')
    assert matches_pattern('send_message', r'^send_')
    assert not matches_pattern('Bash', r'^R')
    assert not matches_pattern('Bash', '[')


def test_if_condition_parse():
    assert parse_if_condition('Bash(git *)') == ('Bash', 'git *')
    assert parse_if_condition('Bash') is None


def test_if_matches_tool_and_args():
    assert if_matches('Bash(git *)', 'Bash', {'command': 'git status'})
    assert not if_matches('Bash(git *)', 'Bash', {'command': 'npm test'})
    assert not if_matches('Bash(git *)', 'Read', {'command': 'git status'})
    assert if_matches('Bash()', 'Bash', {})


def test_if_falls_back_to_matcher():
    assert if_matches('Bash', 'Bash', {})


def test_if_only_applies_to_tool_events():
    assert if_condition_applies('PreToolUse')
    assert if_condition_applies('PostToolUse')
    assert if_condition_applies('PostToolUseFailure')
    assert not if_condition_applies('UserPromptSubmit')
    assert not if_condition_applies('Stop')
