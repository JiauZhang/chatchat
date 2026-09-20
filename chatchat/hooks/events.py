from dataclasses import dataclass, field

HOOK_EVENTS = (
    'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'Notification',
    'UserPromptSubmit', 'SessionStart', 'SessionEnd', 'Stop', 'StopFailure',
    'SubagentStart', 'SubagentStop', 'PreCompact', 'PostCompact',
    'PermissionRequest', 'PermissionDenied', 'Setup', 'TeammateIdle',
    'TaskCreated', 'TaskCompleted', 'Elicitation', 'ElicitationResult',
    'ConfigChange', 'WorktreeCreate', 'WorktreeRemove', 'InstructionsLoaded',
    'CwdChanged', 'FileChanged',
)

ALWAYS_EMITTED_HOOK_EVENTS = ('SessionStart', 'Setup')

MAX_PENDING_EVENTS = 100


@dataclass
class HookStartedEvent:
    type: str = 'started'
    hook_id: str = ''
    hook_name: str = ''
    hook_event: str = ''


@dataclass
class HookResponseEvent:
    type: str = 'response'
    hook_id: str = ''
    hook_name: str = ''
    hook_event: str = ''
    output: str = ''
    stdout: str = ''
    stderr: str = ''
    exit_code: int | None = None
    outcome: str = ''


HookExecutionEvent = HookStartedEvent | HookResponseEvent

_pending_events: list[HookExecutionEvent] = []
_event_handler = None
_all_hook_events_enabled = True


AGENT_TEXT = 'agent.text'
AGENT_REASON_START = 'agent.reason_start'
AGENT_TURN_FINISHED = 'agent.turn_finished'
AGENT_WARN = 'agent.warn'
AGENT_TOOL_CALL = 'agent.tool_call'
AGENT_TOOL_RESULT = 'agent.tool_result'
AGENT_PROGRESS = 'agent.progress'
AGENT_STATE = 'agent.state'
TEAM_SETTLED = 'team.settled'
AGENT_JOB = 'agent.job'


@dataclass
class RuntimeEvent:
    kind: str
    agent: str = ''
    data: dict = field(default_factory=dict)


_runtime_sinks: list = []
_runtime_pending: list[RuntimeEvent] = []


def register_runtime_handler(fn):
    if fn in _runtime_sinks:
        return lambda: None
    _runtime_sinks.append(fn)
    if _runtime_pending and _runtime_sinks:
        for ev in _runtime_pending.copy():
            fn(ev)
        _runtime_pending.clear()
    return lambda: _runtime_sinks.remove(fn)


def clear_runtime_sinks():
    _runtime_sinks.clear()
    _runtime_pending.clear()


def emit(kind: str, *, agent: str = '', **fields):
    ev = RuntimeEvent(kind, agent=agent, data=fields)
    if _runtime_sinks:
        for fn in list(_runtime_sinks):
            fn(ev)
    else:
        _runtime_pending.append(ev)
        if len(_runtime_pending) > MAX_PENDING_EVENTS:
            _runtime_pending.pop(0)


def register_hook_event_handler(handler):
    global _event_handler
    _event_handler = handler
    if handler and _pending_events:
        for event in _pending_events.copy():
            handler(event)
        _pending_events.clear()


def set_all_hook_events_enabled(enabled: bool):
    global _all_hook_events_enabled
    _all_hook_events_enabled = enabled


def _should_emit(hook_event: str) -> bool:
    if hook_event in ALWAYS_EMITTED_HOOK_EVENTS:
        return True
    return _all_hook_events_enabled and hook_event in HOOK_EVENTS


def _emit(event: HookExecutionEvent):
    if _event_handler:
        _event_handler(event)
    else:
        _pending_events.append(event)
        if len(_pending_events) > MAX_PENDING_EVENTS:
            _pending_events.pop(0)


def emit_started(hook_id: str, hook_name: str, hook_event: str):
    if _should_emit(hook_event):
        _emit(HookStartedEvent(hook_id=hook_id, hook_name=hook_name,
                               hook_event=hook_event))


def emit_response(hook_id: str, hook_name: str, hook_event: str,
                  output: str = '', stdout: str = '', stderr: str = '',
                  exit_code: int | None = None, outcome: str = ''):
    if _should_emit(hook_event):
        _emit(HookResponseEvent(hook_id=hook_id, hook_name=hook_name,
                                hook_event=hook_event, output=output,
                                stdout=stdout, stderr=stderr,
                                exit_code=exit_code, outcome=outcome))
