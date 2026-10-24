"""The hook events a session offers, and what each one matches on.

The event list and the matching rule travel together: an event is a name, and
the name says which field of the hook input a matcher is compared against.
Keeping them in one table is what stops the two from drifting apart - a new
event that matches on something has to say so here, once.
"""

from dataclasses import dataclass

ALWAYS_EMITTED_HOOK_EVENTS = ("SessionStart", "Setup")


@dataclass(frozen=True)
class HookEvent:
    """One event: its name, and the field of the hook input it matches on.

    A matcher is compared against that field and nothing else, so an event
    that matches on nothing matches every hook registered for it.
    """

    name: str
    matches_on: str = ""

    @property
    def matcher_field(self) -> str:
        return self.matches_on


def _event(name: str, matches_on: str = "") -> HookEvent:
    return HookEvent(name=name, matches_on=matches_on)


EVENTS: tuple[HookEvent, ...] = (
    _event("PreToolUse", "tool_name"),
    _event("PostToolUse", "tool_name"),
    _event("PostToolUseFailure", "tool_name"),
    _event("Notification", "notification_type"),
    _event("UserPromptSubmit"),
    _event("SessionStart", "source"),
    _event("SessionEnd", "reason"),
    _event("Stop"),
    _event("StopFailure", "error"),
    _event("SubagentStart", "agent_type"),
    _event("SubagentStop", "agent_type"),
    _event("PreCompact", "trigger"),
    _event("PostCompact", "trigger"),
    _event("PermissionRequest", "tool_name"),
    _event("PermissionDenied", "tool_name"),
    _event("Setup", "trigger"),
    _event("TeammateIdle"),
    _event("TaskCreated"),
    _event("TaskCompleted"),
    _event("Elicitation"),
    _event("ElicitationResult"),
    _event("ConfigChange", "source"),
    _event("WorktreeCreate"),
    _event("WorktreeRemove"),
    _event("InstructionsLoaded", "load_reason"),
    _event("CwdChanged"),
    _event("FileChanged", "file_path"),
)

EVENTS_BY_NAME: dict[str, HookEvent] = {event.name: event for event in EVENTS}

HOOK_EVENTS: tuple[str, ...] = tuple(event.name for event in EVENTS)


def match_query(event: str, hook_input: dict) -> str:
    """What a matcher for this event is compared against.

    An event that matches on a field takes it from the hook input; one that
    matches on nothing matches everything registered for it. FileChanged
    matches on the file's name rather than its whole path, so a matcher names
    a file rather than the directory it happens to live in.
    """
    spec = EVENTS_BY_NAME.get(event)
    if spec is None or not spec.matches_on:
        return ""
    value = hook_input.get(spec.matches_on)
    if value is None:
        return ""
    if event == "FileChanged":
        return str(value).rsplit("/", 1)[-1]
    return str(value)


def is_event(name: str) -> bool:
    return name in EVENTS_BY_NAME
