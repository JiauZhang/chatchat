import asyncio
import json
import os
import re
import time

import aiohttp

from chatchat.hooks.schemas import (DEFAULT_HOOK_SHELL, HookBlockingError,
                                    HookResult, get_hook_display_text)
from chatchat.hooks.output import parse_hook_output, process_hook_result

_PLACEHOLDER_RE = re.compile(r'(?<!\$)\{([a-z_][a-z0-9_]*)\}')
_ENV_VAR_RE = re.compile(r'\$\{(\w+)\}|\$(\w+)')


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
        status = proc.returncode
        aborted = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        status = -1
        stdout = stderr = b''
        aborted = True
    duration = _duration_ms(start)
    if aborted:
        return HookResult(hook=hook, outcome='non_blocking_error',
                          duration_ms=duration,
                          message=f'Hook timed out after {config.timeout or 60}s')
    return process_hook_result(hook, stdout.decode(errors='replace'),
                               stderr.decode(errors='replace'), status,
                               duration)


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


async def exec_prompt_hook(client, hook, hook_input: dict) -> HookResult:
    start = time.monotonic()
    config = hook.config
    prompt = config.prompt.replace('$ARGUMENTS',
                                   json.dumps(hook_input, ensure_ascii=False))
    resp = await client.respond([{'role': 'user', 'content': prompt}])
    text = resp if isinstance(resp, str) else json.dumps(resp,
                                                         ensure_ascii=False)
    parsed = parse_hook_output(text)
    if parsed is not None:
        return process_hook_result(hook, text, '', 0, _duration_ms(start))
    lower = text.strip().lower()
    if lower in ('yes', 'allow', 'true'):
        return HookResult(hook=hook, outcome='success',
                          duration_ms=_duration_ms(start))
    if lower in ('no', 'block', 'false'):
        return HookResult(
            hook=hook, outcome='blocking', duration_ms=_duration_ms(start),
            blocking_error=HookBlockingError(
                'Prompt hook blocked the operation',
                get_hook_display_text(config)))
    if lower == 'ask':
        return HookResult(hook=hook, outcome='blocking', decision='ask',
                          duration_ms=_duration_ms(start),
                          message='Hook requested approval')
    return HookResult(hook=hook, outcome='non_blocking_error',
                      duration_ms=_duration_ms(start),
                      message='Prompt hook returned unrecognized output')


async def exec_agent_hook(team, parent_name: str, hook,
                          hook_input: dict) -> HookResult:
    start = time.monotonic()
    config = hook.config
    prompt = config.prompt.replace('$ARGUMENTS',
                                   json.dumps(hook_input, ensure_ascii=False))
    instruction = ('You are a hook evaluator. Reply with a single JSON object '
                   '{"ok": true|false, "reason": "..."} or plain yes/no.')
    sub = await team.spawn_child(parent_name, instruction, internal=True)
    try:
        text = await sub.chat(prompt)
    finally:
        await sub.stop()
    duration = _duration_ms(start)
    ok = None
    data = None
    try:
        data = json.loads(text.strip())
    except (ValueError, TypeError):
        pass
    if isinstance(data, dict):
        ok = data.get('ok')
    if ok is True:
        return HookResult(hook=hook, outcome='success', duration_ms=duration)
    if ok is False:
        reason = (data.get('reason') if isinstance(data, dict)
                  else '') or 'Agent hook blocked the operation'
        return HookResult(
            hook=hook, outcome='blocking', duration_ms=duration,
            blocking_error=HookBlockingError(
                reason, get_hook_display_text(config)))
    parsed = parse_hook_output(text)
    if parsed is not None:
        return process_hook_result(hook, text, '', 0, duration)
    lower = text.strip().lower()
    if lower in ('yes', 'allow'):
        return HookResult(hook=hook, outcome='success', duration_ms=duration)
    if lower in ('no', 'block'):
        return HookResult(
            hook=hook, outcome='blocking', duration_ms=duration,
            blocking_error=HookBlockingError(
                'Agent hook blocked the operation',
                get_hook_display_text(config)))
    return HookResult(hook=hook, outcome='cancel', duration_ms=duration)


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
                   'updated_input', 'initial_user_message', 'retry'}
        return HookResult(hook=hook, outcome=result.get('outcome') or 'success',
                          **{k: v for k, v in result.items() if k in allowed
                             and k != 'outcome'},
                          duration_ms=_duration_ms(start))
    return HookResult(hook=hook, outcome='success',
                      duration_ms=_duration_ms(start),
                      message=str(result) if result else '')
