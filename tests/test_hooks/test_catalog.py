from chatchat.hooks.catalog import ALWAYS_EMITTED_HOOK_EVENTS, EVENTS, HOOK_EVENTS

# The events claude-code offers, in the order it lists them
# (src/entrypoints/sdk/coreTypes.ts, HOOK_EVENTS).
REFERENCE_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "UserPromptSubmit",
    "SessionStart",
    "SessionEnd",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "PermissionRequest",
    "PermissionDenied",
    "Setup",
    "TeammateIdle",
    "TaskCreated",
    "TaskCompleted",
    "Elicitation",
    "ElicitationResult",
    "ConfigChange",
    "WorktreeCreate",
    "WorktreeRemove",
    "InstructionsLoaded",
    "CwdChanged",
    "FileChanged",
)


def test_the_events_are_the_ones_claude_code_offers():
    """The events a session can fire are the reference's, in its order."""
    assert HOOK_EVENTS == REFERENCE_EVENTS


def test_the_names_and_the_events_are_one_list():
    """The names are what the events are called; a second list saying
    otherwise is how the two drift apart."""
    assert HOOK_EVENTS == tuple(event.name for event in EVENTS)


def test_the_lifecycle_events_are_always_emitted():
    assert ALWAYS_EMITTED_HOOK_EVENTS == ("SessionStart", "Setup")
    assert all(name in HOOK_EVENTS for name in ALWAYS_EMITTED_HOOK_EVENTS)
