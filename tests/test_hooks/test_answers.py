from chatchat.hooks.output import (
    ANSWER_SHAPES,
    aggregate_results,
    parse_hook_output,
    process_hook_result,
)
from chatchat.hooks.schemas import HookCommand, IndividualHookConfig

# The answer each event may carry, as claude-code's schema gives them
# (src/entrypoints/sdk/coreSchemas.ts, the hookSpecificOutput union).
REFERENCE_SHAPES = {
    "PreToolUse": ("permissionDecision", "permissionDecisionReason", "updatedInput", "additionalContext"),
    "UserPromptSubmit": ("additionalContext",),
    "SessionStart": ("additionalContext", "initialUserMessage", "watchPaths"),
    "Setup": ("additionalContext",),
    "SubagentStart": ("additionalContext",),
    "PostToolUse": ("additionalContext", "updatedMCPToolOutput"),
    "PostToolUseFailure": ("additionalContext",),
    "PermissionDenied": ("retry",),
    "Notification": ("additionalContext",),
    "PermissionRequest": ("decision",),
    "Elicitation": ("action", "content"),
    "ElicitationResult": ("action", "content"),
    "CwdChanged": ("watchPaths",),
    "FileChanged": ("watchPaths",),
    "WorktreeCreate": ("worktreePath",),
}


def make_hook(command="echo hi", event="PreToolUse"):
    return IndividualHookConfig(event=event, matcher="*", hook_id="t1", config=HookCommand(type="command", command=command))


def test_the_answers_are_the_shapes_the_reference_allows():
    """An answer is read against the event it answers; the reference gives
    every event its own shape, and a shape we do not know is not a shape."""
    assert ANSWER_SHAPES == REFERENCE_SHAPES


def test_a_pre_tool_use_hook_may_ask():
    """'ask' is a decision the reference makes: the hook wants the person to
    decide, so the answer is not dropped as malformed."""
    out = parse_hook_output(
        '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"}}',
        event="PreToolUse",
    )
    assert out.permission == "ask"


def test_a_permission_denied_hook_may_ask_for_a_retry():
    out = parse_hook_output(
        '{"hookSpecificOutput": {"hookEventName": "PermissionDenied", "retry": true}}',
        event="PermissionDenied",
    )
    assert out.retry is True


def test_a_worktree_create_hook_may_name_the_directory():
    out = parse_hook_output(
        '{"hookSpecificOutput": {"hookEventName": "WorktreeCreate", "worktreePath": "/tmp/w"}}',
        event="WorktreeCreate",
    )
    assert out.worktree_path == "/tmp/w"


def test_a_permission_request_behavior_is_allow_or_deny():
    """The reference's permission request answers with one of two things; it
    is not the permission decision, which has three."""
    text = '{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "ask"}}}'
    try:
        parse_hook_output(text, event="PermissionRequest")
    except ValueError as exc:
        assert "behavior" in str(exc)
    else:
        raise AssertionError("a permission request may not ask")


def test_a_permission_decision_may_not_be_something_else():
    text = '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "maybe"}}'
    try:
        parse_hook_output(text, event="PreToolUse")
    except ValueError as exc:
        assert "permissionDecision" in str(exc)
    else:
        raise AssertionError("a permission decision must be one of the three")


def test_a_deny_beats_an_ask_beats_an_allow():
    """The reference settles several answers with the strongest one first."""

    def result(event, text):
        return process_hook_result(make_hook(event=event), text, "", 0, 5)

    allow = result("PreToolUse", '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}')
    ask = result("PreToolUse", '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"}}')
    deny = result("PreToolUse", '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"}}')

    assert aggregate_results([allow, ask]).decision == "ask"
    assert aggregate_results([allow, deny]).decision == "deny"
    assert aggregate_results([ask, deny]).decision == "deny"


def test_a_retry_survives_the_aggregate():
    hook = make_hook(event="PermissionDenied")
    result = process_hook_result(
        hook,
        '{"hookSpecificOutput": {"hookEventName": "PermissionDenied", "retry": true}}',
        "",
        0,
        5,
    )
    assert aggregate_results([result]).retry is True


# What a permission update is, as the reference defines it
# (src/utils/permissions/PermissionUpdateSchema.ts).
def _request_answer(decision: str) -> str:
    return '{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": ' + decision + "}}"


def test_a_permission_request_may_hand_back_the_rules_it_wants_kept():

    text = _request_answer(
        '{"behavior": "allow", "updatedPermissions": [{"type": "addRules", '
        '"rules": [{"toolName": "Read", "ruleContent": "./docs/**"}], '
        '"behavior": "allow", "destination": "localSettings"}]}'
    )
    result = process_hook_result(make_hook(event="PermissionRequest"), text, "", 0, 5)
    assert result.decision == "allow"
    assert result.updated_permissions == [
        {
            "type": "addRules",
            "rules": [{"toolName": "Read", "ruleContent": "./docs/**"}],
            "behavior": "allow",
            "destination": "localSettings",
        }
    ]


def test_a_permission_update_is_one_of_the_six_kinds_the_reference_has():

    text = _request_answer(
        '{"behavior": "allow", "updatedPermissions": [{"type": "eraseRules", '
        '"rules": [], "behavior": "allow", "destination": "session"}]}'
    )
    result = process_hook_result(make_hook(event="PermissionRequest"), text, "", 0, 5)
    assert result.outcome == "non_blocking_error"
    assert "eraseRules" in result.message


def test_a_permission_update_names_a_destination_the_reference_has():

    text = _request_answer(
        '{"behavior": "allow", "updatedPermissions": [{"type": "addRules", '
        '"rules": [{"toolName": "Read"}], "behavior": "allow", "destination": "somewhere"}]}'
    )
    result = process_hook_result(make_hook(event="PermissionRequest"), text, "", 0, 5)
    assert result.outcome == "non_blocking_error"
    assert "somewhere" in result.message


def test_every_update_a_permission_request_hands_back_survives_the_aggregate():

    def answer(rules: str):
        return process_hook_result(
            make_hook(event="PermissionRequest"),
            _request_answer('{"behavior": "allow", "updatedPermissions": [' + rules + "]}"),
            "",
            0,
            5,
        )

    first = answer('{"type": "addRules", "rules": [{"toolName": "Read"}], "behavior": "allow", "destination": "session"}')
    second = answer('{"type": "setMode", "mode": "acceptEdits", "destination": "session"}')
    assert len(aggregate_results([first, second]).updated_permissions) == 2
