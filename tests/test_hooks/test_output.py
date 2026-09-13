from chatchat.hooks.output import (aggregate_results, get_pre_tool_hook_blocking_message,
                                   parse_hook_output, process_hook_result)
from chatchat.hooks.schemas import HookBlockingError, HookCommand, \
    IndividualHookConfig


def make_hook(command='echo hi', htype='command'):
    return IndividualHookConfig(event='PreToolUse', matcher='*', hook_id='t1',
                                config=HookCommand(type=htype, command=command))


def test_parse_json_output():
    out = parse_hook_output('{"decision": "block", "reason": "nope"}')
    assert out is not None
    assert out.decision == 'block'
    assert out.reason == 'nope'
    assert parse_hook_output('plain text') is None
    assert parse_hook_output('{bad json') is None


def test_exit_zero_success():
    r = process_hook_result(make_hook(), 'ok', '', 0, 5)
    assert r.outcome == 'success'
    assert r.message == 'ok'


def test_exit_two_blocks():
    r = process_hook_result(make_hook(), '', 'denied', 2, 5)
    assert r.outcome == 'blocking'
    assert 'denied' in r.blocking_error.blocking_error


def test_other_exit_non_blocking():
    r = process_hook_result(make_hook(), '', 'boom', 1, 5)
    assert r.outcome == 'non_blocking_error'


def test_json_wins_over_exit_code():
    r = process_hook_result(make_hook(), '{"decision": "allow"}', '', 2, 5)
    assert r.outcome == 'success'
    assert r.decision == 'allow'


def test_json_block():
    r = process_hook_result(make_hook(), '{"decision": "block", "reason": "r"}', '', 0, 5)
    assert r.outcome == 'blocking'
    assert r.blocking_error.blocking_error == 'r'


def test_json_continue_false_cancels():
    r = process_hook_result(make_hook(), '{"continue": false}', '', 0, 5)
    assert r.outcome == 'cancel'


def test_aggregate_block_precedence():
    allow = process_hook_result(make_hook(), '{"decision": "allow"}', '', 0, 5)
    block = process_hook_result(make_hook(), '{"decision": "block"}', '', 0, 5)
    agg = aggregate_results([allow, block])
    assert agg.decision == 'block'
    assert agg.blocking_error is not None
    assert not agg.success


def test_aggregate_updated_input():
    allow = process_hook_result(make_hook(), '{"decision": "allow", "updatedInput": {"a": 1}}', '', 0, 5)
    agg = aggregate_results([allow])
    assert agg.updated_input == {'a': 1}


def test_aggregate_continue_loop():
    cancel = process_hook_result(make_hook(), '{"continue": false}', '', 0, 5)
    agg = aggregate_results([cancel])
    assert not agg.continue_loop


def test_blocking_message_builder():
    be = HookBlockingError('no', 'echo hi')
    assert get_pre_tool_hook_blocking_message('Bash', be) == 'Bash hook error: no'
