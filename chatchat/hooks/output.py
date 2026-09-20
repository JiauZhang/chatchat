import json
from dataclasses import dataclass

from chatchat.hooks.schemas import (AggregatedHookResult, HookBlockingError,
                                    HookResult, get_hook_display_text)

DECISIONS = ('approve', 'block')
PERMISSION_DECISIONS = ('allow', 'deny')

PAYLOAD_KEYS = {
    'PreToolUse': ('permissionDecision', 'permissionDecisionReason',
                   'updatedInput', 'additionalContext'),
    'PostToolUse': ('additionalContext',),
    'PostToolUseFailure': ('additionalContext',),
    'UserPromptSubmit': ('additionalContext',),
    'SessionStart': ('additionalContext',),
    'Setup': ('additionalContext',),
    'SubagentStart': ('additionalContext',),
    'PermissionRequest': ('decision',),
}


class HookContractError(ValueError):
    pass


@dataclass
class HookOutput:
    permission: str = ''
    reason: str = ''
    additional_context: str = ''
    updated_input: dict | None = None
    system_message: str = ''
    suppress_output: bool = False
    stop_: bool = False
    stop_reason: str = ''


def _payload(data: dict, event: str | None) -> HookOutput:
    out = HookOutput()
    specific = data.get('hookSpecificOutput')
    if specific is None:
        return out
    if not isinstance(specific, dict):
        raise HookContractError('hookSpecificOutput must be an object')
    name = specific.get('hookEventName')
    if not name:
        raise HookContractError('hookSpecificOutput needs a hookEventName')
    if event is not None and name != event:
        raise HookContractError(
            f'hook answered for "{name}" but ran on "{event}"')
    allowed = PAYLOAD_KEYS.get(name)
    if allowed is None:
        raise HookContractError(f'"{name}" takes no hookSpecificOutput')
    unknown = set(specific) - set(allowed) - {'hookEventName'}
    if unknown:
        raise HookContractError(
            f'"{name}" does not carry {sorted(unknown)}')
    if name == 'PermissionRequest':
        decision = specific.get('decision')
        if not isinstance(decision, dict):
            raise HookContractError('decision must be an object')
        behavior = decision.get('behavior')
        if behavior not in PERMISSION_DECISIONS:
            raise HookContractError(
                f'behavior must be one of {list(PERMISSION_DECISIONS)}, '
                f'got {behavior!r}')
        out.permission = behavior
        if behavior == 'allow':
            updated = decision.get('updatedInput')
            if updated is not None:
                if not isinstance(updated, dict):
                    raise HookContractError('updatedInput must be an object')
                out.updated_input = updated
        else:
            out.reason = str(decision.get('message') or '')
        return out
    if specific.get('permissionDecision') is not None:
        decision = specific['permissionDecision']
        if decision not in PERMISSION_DECISIONS:
            raise HookContractError(
                f'permissionDecision must be one of '
                f'{list(PERMISSION_DECISIONS)}, got {decision!r}')
        out.permission = decision
        out.reason = (specific.get('permissionDecisionReason')
                      or data.get('reason') or '')
    if specific.get('updatedInput') is not None:
        updated = specific['updatedInput']
        if not isinstance(updated, dict):
            raise HookContractError('updatedInput must be an object')
        out.updated_input = updated
    out.additional_context = specific.get('additionalContext') or ''
    return out


def parse_hook_output(stdout: str, event: str | None = None) -> HookOutput | None:
    text = stdout.strip()
    if not text.startswith('{'):
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    out = _payload(data, event)
    if data.get('continue') is False:
        out.stop_ = True
        out.stop_reason = str(data.get('stopReason') or '')
    out.suppress_output = bool(data.get('suppressOutput'))
    out.system_message = data.get('systemMessage') or ''
    decision = data.get('decision')
    if decision is not None:
        if decision not in DECISIONS:
            raise HookContractError(
                f'decision must be one of {list(DECISIONS)}, got '
                f'{decision!r}')
        if not out.permission:
            out.permission = 'allow' if decision == 'approve' else 'deny'
            out.reason = data.get('reason') or ''
    return out


def process_hook_result(hook, stdout: str, stderr: str, exit_code: int,
                        duration_ms: int) -> HookResult:
    hook_name = get_hook_display_text(hook.config)
    base = {'hook': hook, 'exit_code': exit_code, 'duration_ms': duration_ms,
            'stdout': stdout, 'stderr': stderr}
    try:
        parsed = parse_hook_output(stdout, hook.event)
    except HookContractError as e:
        return HookResult(outcome='non_blocking_error',
                          message=f'{hook_name}: {e}', **base)
    if parsed is not None:
        if parsed.stop_:
            return HookResult(outcome='cancel', message=parsed.stop_reason,
                              stop_reason=parsed.stop_reason,
                              system_message=parsed.system_message, **base)
        if parsed.permission == 'deny':
            return HookResult(
                outcome='blocking', decision='deny',
                blocking_error=HookBlockingError(
                    parsed.reason or stderr or 'Hook blocked the operation',
                    hook_name),
                system_message=parsed.system_message,
                suppress_output=parsed.suppress_output, **base)
        return HookResult(
            outcome='success', decision=parsed.permission,
            additional_context=parsed.additional_context,
            updated_input=parsed.updated_input,
            system_message=parsed.system_message,
            suppress_output=parsed.suppress_output,
            message='' if parsed.suppress_output else stdout.strip(), **base)
    if exit_code == 0:
        return HookResult(outcome='success', message=stdout.strip(), **base)
    if exit_code == 2:
        reason = stderr or 'the hook wrote no reason on stderr'
        return HookResult(
            outcome='blocking',
            blocking_error=HookBlockingError(f'[{hook_name}]: {reason}',
                                             hook_name),
            **base)
    return HookResult(
        outcome='non_blocking_error',
        message=f'{hook_name} failed: {stderr.strip() or "nothing on stderr"}',
        **base)


def aggregate_results(results: list[HookResult],
                      total_ms: int = 0) -> AggregatedHookResult:
    decision = ''
    for d in ('deny', 'allow'):
        if any(r.decision == d for r in results):
            decision = d
            break
    blocking = next((r for r in results if r.outcome == 'blocking'), None)
    stopped = next((r for r in results
                    if r.outcome == 'cancel' or r.stop_reason), None)
    updated = next((r.updated_input for r in results
                    if r.updated_input is not None), None)
    return AggregatedHookResult(
        results=results, decision=decision,
        continue_loop=stopped is None,
        stop_reason=stopped.stop_reason if stopped else '',
        system_message='\n'.join(r.system_message for r in results
                                 if r.system_message),
        suppress_output=any(r.suppress_output for r in results),
        blocking_error=blocking.blocking_error if blocking else None,
        additional_context='\n'.join(r.additional_context for r in results
                                     if r.additional_context),
        updated_input=updated, total_duration_ms=total_ms)


def describe_blocking(be: HookBlockingError) -> str:
    return f'{be.command} said: {be.blocking_error}'
