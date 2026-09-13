import json
from dataclasses import dataclass, field

from chatchat.hooks.schemas import (AggregatedHookResult, HookBlockingError,
                                    HookResult, get_hook_display_text)


@dataclass
class HookOutput:
    decision: str = ''
    continue_: bool | None = None
    suppress_output: bool = False
    status_message: str = ''
    system_message: str = ''
    additional_context: str = ''
    reason: str = ''
    updated_input: dict | None = None
    initial_user_message: str = ''
    retry: bool = False


def parse_hook_output(stdout: str) -> HookOutput | None:
    text = stdout.strip()
    if not text.startswith('{'):
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return HookOutput(
        decision=data.get('decision') or '',
        continue_=data.get('continue'),
        suppress_output=bool(data.get('suppressOutput')),
        status_message=data.get('statusMessage') or '',
        system_message=data.get('systemMessage') or '',
        additional_context=data.get('additionalContext') or '',
        reason=data.get('reason') or '',
        updated_input=data.get('updatedInput'),
        initial_user_message=data.get('initialUserMessage') or '',
        retry=bool(data.get('retry')),
    )


def process_hook_result(hook, stdout: str, stderr: str, exit_code: int,
                        duration_ms: int) -> HookResult:
    hook_name = get_hook_display_text(hook.config)
    parsed = parse_hook_output(stdout)
    if parsed is not None:
        if parsed.continue_ is False:
            return HookResult(hook=hook, outcome='cancel', exit_code=exit_code,
                              duration_ms=duration_ms, stdout=stdout,
                              stderr=stderr)
        if parsed.decision == 'block':
            reason = parsed.reason or stderr or 'Hook blocked the operation'
            return HookResult(
                hook=hook, outcome='blocking', decision='block',
                exit_code=exit_code, duration_ms=duration_ms, stdout=stdout,
                stderr=stderr,
                blocking_error=HookBlockingError(reason, hook_name))
        if parsed.decision == 'ask':
            msg = 'Hook requested approval: ' + (parsed.reason
                                                 or parsed.status_message)
            return HookResult(hook=hook, outcome='blocking', decision='ask',
                              message=msg, exit_code=exit_code,
                              duration_ms=duration_ms, stdout=stdout,
                              stderr=stderr)
        return HookResult(
            hook=hook, outcome='success', decision='allow',
            suppress_output=parsed.suppress_output,
            system_message=parsed.system_message,
            additional_context=parsed.additional_context,
            updated_input=parsed.updated_input,
            initial_user_message=parsed.initial_user_message,
            retry=parsed.retry, exit_code=exit_code,
            duration_ms=duration_ms, stdout=stdout, stderr=stderr,
            message=parsed.status_message)
    if exit_code == 0:
        return HookResult(hook=hook, outcome='success', exit_code=exit_code,
                          duration_ms=duration_ms, stdout=stdout,
                          stderr=stderr, message=stdout.strip())
    if exit_code == 2:
        err = stderr or 'No stderr output'
        return HookResult(
            hook=hook, outcome='blocking', exit_code=exit_code,
            duration_ms=duration_ms, stdout=stdout, stderr=stderr,
            blocking_error=HookBlockingError(f'[{hook_name}]: {err}',
                                             hook_name))
    return HookResult(
        hook=hook, outcome='non_blocking_error', exit_code=exit_code,
        duration_ms=duration_ms, stdout=stdout, stderr=stderr,
        message=f'Failed with non-blocking status code: {stderr.strip() or "No stderr output"}')


def aggregate_results(results: list[HookResult],
                      total_ms: int = 0) -> AggregatedHookResult:
    decision = ''
    for d in ('block', 'ask', 'allow'):
        if any(r.decision == d for r in results):
            decision = d
            break
    blocking = next((r for r in results if r.outcome == 'blocking'), None)
    updated = next((r.updated_input for r in results
                    if r.updated_input is not None), None)
    return AggregatedHookResult(
        results=results, decision=decision,
        continue_loop=all(r.outcome != 'cancel' for r in results),
        suppress_output=any(r.suppress_output for r in results),
        blocking_error=blocking.blocking_error if blocking else None,
        updated_input=updated, total_duration_ms=total_ms)


def get_pre_tool_hook_blocking_message(hook_name: str,
                                       be: HookBlockingError) -> str:
    return f'{hook_name} hook error: {be.blocking_error}'


def get_user_prompt_submit_hook_blocking_message(be: HookBlockingError) -> str:
    return f'UserPromptSubmit operation blocked by hook:\n{be.blocking_error}'


def get_stop_hook_message(be: HookBlockingError) -> str:
    return f'Stop hook feedback:\n{be.blocking_error}'
