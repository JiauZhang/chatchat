import pytest

from chatchat.hooks.output import (aggregate_results, parse_hook_output,
                                   process_hook_result)
from chatchat.hooks.schemas import HookCommand, IndividualHookConfig


def make_hook(command='echo hi', event='PreToolUse'):
    return IndividualHookConfig(event=event, matcher='*', hook_id='t1',
                                config=HookCommand(type='command', command=command))


def test_plain_text_output_is_not_json():
    assert parse_hook_output('plain text') is None
    assert parse_hook_output('{bad json') is None


def test_top_level_decision_only_approves_or_blocks():
    out = parse_hook_output('{"decision": "block", "reason": "nope"}')
    assert out.permission == 'deny'
    assert out.reason == 'nope'
    assert parse_hook_output('{"decision": "approve"}').permission == 'allow'
    with pytest.raises(ValueError):
        parse_hook_output('{"decision": "maybe"}')


def test_permission_decision_arrives_in_the_event_payload():
    text = ('{"hookSpecificOutput": {"hookEventName": "PreToolUse",'
            ' "permissionDecision": "deny",'
            ' "permissionDecisionReason": "because"}}')
    out = parse_hook_output(text, event='PreToolUse')
    assert out.permission == 'deny'
    assert out.reason == 'because'


def test_event_payload_must_name_the_event_that_ran():
    text = ('{"hookSpecificOutput": {"hookEventName": "PostToolUse",'
            ' "additionalContext": "x"}}')
    with pytest.raises(ValueError):
        parse_hook_output(text, event='PreToolUse')


def test_payload_fields_only_belong_to_their_own_event():
    text = ('{"hookSpecificOutput": {"hookEventName": "SessionStart",'
            ' "permissionDecision": "deny"}}')
    with pytest.raises(ValueError):
        parse_hook_output(text, event='SessionStart')


def test_context_and_rewritten_input_come_from_the_payload():
    text = ('{"hookSpecificOutput": {"hookEventName": "PreToolUse",'
            ' "additionalContext": "note", "updatedInput": {"a": 1}}}')
    out = parse_hook_output(text, event='PreToolUse')
    assert out.additional_context == 'note'
    assert out.updated_input == {'a': 1}
    flat = parse_hook_output('{"additionalContext": "note"}',
                             event='PreToolUse')
    assert flat.additional_context == ''


def test_continue_false_carries_the_stop_reason():
    out = parse_hook_output('{"continue": false, "stopReason": "done here"}')
    assert out.stop_ is True
    assert out.stop_reason == 'done here'
    assert parse_hook_output('{"continue": true}').stop_ is False


def test_wiring_fields_reach_the_user():
    out = parse_hook_output('{"systemMessage": "heads up",'
                            ' "suppressOutput": true}')
    assert out.system_message == 'heads up'
    assert out.suppress_output is True


def test_exit_zero_success_keeps_stdout_as_the_message():
    r = process_hook_result(make_hook(), 'ok', '', 0, 5)
    assert r.outcome == 'success'
    assert r.message == 'ok'


def test_exit_two_blocks_with_the_stderr_reason():
    r = process_hook_result(make_hook(), '', 'denied', 2, 5)
    assert r.outcome == 'blocking'
    assert 'denied' in r.blocking_error.blocking_error


def test_other_exit_is_a_non_blocking_error():
    r = process_hook_result(make_hook(), '', 'boom', 1, 5)
    assert r.outcome == 'non_blocking_error'


def test_json_decision_wins_over_the_exit_code():
    r = process_hook_result(make_hook(), '{"decision": "approve"}', '', 2, 5)
    assert r.outcome == 'success'
    assert r.decision == 'allow'


def test_json_block_carries_the_reason():
    r = process_hook_result(
        make_hook(), '{"decision": "block", "reason": "r"}', '', 0, 5)
    assert r.outcome == 'blocking'
    assert r.blocking_error.blocking_error == 'r'


def test_a_broken_contract_is_reported_not_swallowed():
    r = process_hook_result(make_hook(), '{"decision": "approve-ish"}', '', 0, 5)
    assert r.outcome == 'non_blocking_error'
    assert 'approve' in r.message


def test_suppressed_output_stays_out_of_the_message():
    r = process_hook_result(make_hook(),
                            '{"suppressOutput": true}', 'quiet', 0, 5)
    assert r.suppress_output is True
    assert r.message == ''


def test_aggregate_block_precedence():
    allow = process_hook_result(make_hook(), '{"decision": "approve"}', '', 0, 5)
    block = process_hook_result(make_hook(), '{"decision": "block"}', '', 0, 5)
    agg = aggregate_results([allow, block])
    assert agg.decision == 'deny'
    assert agg.blocking_error is not None
    assert not agg.success


def test_aggregate_updated_input():
    text = ('{"hookSpecificOutput": {"hookEventName": "PreToolUse",'
            ' "permissionDecision": "allow", "updatedInput": {"a": 1}}}')
    agg = aggregate_results([process_hook_result(make_hook(), text, '', 0, 5)])
    assert agg.decision == 'allow'
    assert agg.updated_input == {'a': 1}


def test_continue_false_cancels_and_the_aggregate_keeps_the_reason():
    cancel = process_hook_result(
        make_hook(), '{"continue": false, "stopReason": "done here"}', '', 0, 5)
    assert cancel.outcome == 'cancel'
    agg = aggregate_results([cancel])
    assert not agg.continue_loop
    assert agg.stop_reason == 'done here'


def test_a_hook_that_says_nothing_decides_nothing():
    silent = process_hook_result(make_hook(), '', '', 0, 5)
    assert silent.decision == ''
    assert aggregate_results([silent]).decision == ''


def _permission_request(text):
    return process_hook_result(make_hook(event='PermissionRequest'), text,
                               '', 0, 5)


def test_a_permission_request_hook_can_allow_and_rewrite_the_input():
    text = ('{"hookSpecificOutput": {"hookEventName": "PermissionRequest",'
            ' "decision": {"behavior": "allow", "updatedInput": {"a": 1}}}}')
    r = _permission_request(text)
    assert r.decision == 'allow'
    assert r.updated_input == {'a': 1}
    assert r.blocking_error is None


def test_a_permission_request_deny_carries_its_message():
    text = ('{"hookSpecificOutput": {"hookEventName": "PermissionRequest",'
            ' "decision": {"behavior": "deny", "message": "not this one"}}}')
    r = _permission_request(text)
    assert r.decision == 'deny'
    assert r.blocking_error.blocking_error == 'not this one'
    assert aggregate_results([r]).decision == 'deny'


def test_an_unknown_permission_request_behavior_is_a_contract_error():
    text = ('{"hookSpecificOutput": {"hookEventName": "PermissionRequest",'
            ' "decision": {"behavior": "maybe"}}}')
    r = _permission_request(text)
    assert r.outcome == 'non_blocking_error'
    assert 'behavior' in r.message


def test_a_permission_request_decision_must_be_an_object():
    text = ('{"hookSpecificOutput": {"hookEventName": "PermissionRequest",'
            ' "decision": "allow"}}')
    r = _permission_request(text)
    assert r.outcome == 'non_blocking_error'
    assert 'object' in r.message
