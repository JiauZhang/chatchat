import asyncio
import json
import os
import re
import time

import aiohttp

from chatchat.hooks.schemas import (DEFAULT_HOOK_SHELL, HookBlockingError,
                                    HookResult, get_hook_display_text)
from chatchat.hooks.output import process_hook_result

_PLACEHOLDER_RE = re.compile(r'(?<!\$)\{([a-z_][a-z0-9_]*)\}')
_ENV_VAR_RE = re.compile(r'\$\{(\w+)\}|\$(\w+)')

EVALUATOR_INSTRUCTION = (
    'You are evaluating a hook condition. Reply with a single JSON object: '
    '{"ok": true} when the condition holds, or {"ok": false, '
    '"reason": "why it does not"} when it does not.')


def substitute_template(text: str, hook_input: dict) -> str:
    def repl(m):
        key = m.group(1)
        if key not in hook_input:
            return m.group(0)
        value = hook_input[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _PLACEHOLDER_RE.sub(repl, text)


def _interpolate_headers(headers: dict, allowed_env_vars: list) -> dict:
    allowed = set(allowed_env_vars or [])
    out = {}
    for key, value in (headers or {}).items():
        def repl(m):
            name = m.group(1) or m.group(2)
            return os.environ.get(name, '') if name in allowed else ''

        value = _ENV_VAR_RE.sub(repl, value)
        out[key] = value.replace('\r', '').replace('\n', '').replace('\x00', '')
    return out


def _duration_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


async def exec_command_hook(hook, hook_input: dict, cwd: str) -> HookResult:
    start = time.monotonic()
    config = hook.config
    command = substitute_template(config.command, hook_input)
    env = {**os.environ, 'CHATCHAT_PROJECT_DIR': str(cwd)}
    executable = '/bin/bash' if config.shell == DEFAULT_HOOK_SHELL else None
    proc = await asyncio.create_subprocess_shell(
        command, executable=executable, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    return process_hook_result(hook, stdout.decode(errors='replace'),
                               stderr.decode(errors='replace'),
                               proc.returncode, _duration_ms(start))


async def exec_http_hook(hook, hook_input: dict) -> HookResult:
    start = time.monotonic()
    config = hook.config
    headers = _interpolate_headers(config.headers, config.allowed_env_vars)
    timeout = aiohttp.ClientTimeout(total=config.timeout or 600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(config.url, json=hook_input,
                                headers=headers) as resp:
            body = await resp.text()
            status = resp.status
    return process_hook_result(hook, body, '', 0 if 200 <= status < 300 else 1,
                               _duration_ms(start))


def substitute_args(prompt: str, hook_input: dict) -> str:
    return prompt.replace('$ARGUMENTS',
                          json.dumps(hook_input, ensure_ascii=False))


def _condition_result(hook, text: str, duration_ms: int) -> HookResult:
    try:
        data = json.loads(text.strip())
    except (ValueError, TypeError, AttributeError):
        data = None
    ok = data.get('ok') if isinstance(data, dict) else None
    name = get_hook_display_text(hook.config)
    if ok is True:
        return HookResult(hook=hook, outcome='success', duration_ms=duration_ms)
    if ok is False:
        reason = data.get('reason') or 'the hook gave no reason'
        return HookResult(
            hook=hook, outcome='blocking', duration_ms=duration_ms,
            stop_reason=reason if isinstance(reason, str) else str(reason),
            blocking_error=HookBlockingError(
                f'{name}: condition not met: {reason}', name))
    return HookResult(hook=hook, outcome='non_blocking_error',
                      duration_ms=duration_ms,
                      message=f'{name}: expected {{"ok": ...}} JSON, got '
                              f'{text.strip()[:200] or "nothing"}')


async def exec_prompt_hook(client, hook, hook_input: dict) -> HookResult:
    start = time.monotonic()
    messages = list(hook_input.get('messages') or [])
    messages.append({'role': 'user',
                     'content': substitute_args(hook.config.prompt,
                                                hook_input)})
    resp = await client.respond(messages)
    text = resp if isinstance(resp, str) else json.dumps(resp,
                                                         ensure_ascii=False)
    return _condition_result(hook, text, _duration_ms(start))


async def exec_agent_hook(team, parent_name: str, hook,
                          hook_input: dict) -> HookResult:
    start = time.monotonic()
    sub = await team.spawn_child(parent_name, EVALUATOR_INSTRUCTION,
                                 internal=True)
    try:
        text = await sub.chat(substitute_args(hook.config.prompt, hook_input))
    finally:
        await sub.stop()
    return _condition_result(hook, text, _duration_ms(start))


async def exec_function_hook(hook, hook_input: dict) -> HookResult:
    start = time.monotonic()
    config = hook.config
    if asyncio.iscoroutinefunction(config.fn):
        result = await config.fn(hook_input)
    else:
        result = await asyncio.to_thread(config.fn, hook_input)
    if result is False:
        return HookResult(
            hook=hook, outcome='blocking', duration_ms=_duration_ms(start),
            blocking_error=HookBlockingError(
                config.error_message or 'Hook blocked operation',
                get_hook_display_text(config)))
    if result is None or result is True:
        return HookResult(hook=hook, outcome='success',
                          duration_ms=_duration_ms(start))
    if isinstance(result, dict):
        result = json.dumps(result, ensure_ascii=False)
    return process_hook_result(hook, str(result), '', 0, _duration_ms(start))


async def exec_callback_hook(hook, event: str, hook_input: dict) -> HookResult:
    start = time.monotonic()
    config = hook.config
    if asyncio.iscoroutinefunction(config.fn):
        result = await config.fn(event, hook_input)
    else:
        result = await asyncio.to_thread(config.fn, event, hook_input)
    if isinstance(result, dict):
        allowed = {'outcome', 'message', 'system_message', 'blocking_error',
                   'suppress_output', 'stdout', 'stderr', 'exit_code',
                   'duration_ms', 'decision', 'additional_context',
                   'updated_input', 'stop_reason'}
        return HookResult(hook=hook, outcome=result.get('outcome') or 'success',
                          **{k: v for k, v in result.items() if k in allowed
                             and k != 'outcome'},
                          duration_ms=_duration_ms(start))
    return HookResult(hook=hook, outcome='success',
                      duration_ms=_duration_ms(start),
                      message=str(result) if result else '')
