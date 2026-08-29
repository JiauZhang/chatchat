from chatchat.core.event import Event


def _tokens(ev: Event, tag: str):
    usage = ev.data.get('usage')
    if usage:
        print(f'[{ev.source:<10}  {tag:>12}] '
              f'prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}')


def _on_client_start(ev: Event):
    print(f'[{ev.source:<10}  {"client:start":>12}]')


def _on_client_error(ev: Event):
    error = ev.data.get('error', '')
    print(f'[{ev.source:<10}  {"client:error":>12}] {error}')


def _on_client_retry(ev: Event):
    print(f'[{ev.source:<10}  {"client:retry":>12}] '
          f'retry {ev.data.get("retry","")}: {ev.data.get("error","")}')


def _on_client_end(ev: Event):
    print(f'[{ev.source:<10}  {"client:end":>12}]')


def _on_client_tokens(ev: Event):
    _tokens(ev, 'client:tokens')


def _on_tool_start(ev: Event):
    print(f'[{ev.source:<10}  {"tool:start":>12}]')


def _on_tool_step(ev: Event):
    print(f'[{ev.source:<10}  {"tool:step":>12}] {ev.data.get("content","")}')


def _on_tool_end(ev: Event):
    result = ev.data.get('result')
    result = '' if result is None else str(result)[:120]
    print(f'[{ev.source:<10}  {"tool:end":>12}] {result}')


def _on_tool_error(ev: Event):
    print(f'[{ev.source:<10}  {"tool:error":>12}] {ev.data.get("name","")}: {ev.data.get("error","")}')


def _on_agent_start(ev: Event):
    print(f'[{ev.source:<10}  {"agent:start":>12}] {ev.data.get("message","")}')


def _on_agent_step(ev: Event):
    if tcs := ev.data.get('tool_calls', []):
        print(f'[{ev.source:<10}  {"agent:step":>12}] {tcs}')


def _on_agent_end(ev: Event):
    print(f'[{ev.source:<10}  {"agent:end":>12}] {ev.data.get("content","")}')


def _on_agent_tokens(ev: Event):
    _tokens(ev, 'agent:tokens')


def _on_team_tokens(ev: Event):
    _tokens(ev, 'team:tokens')


def _on_agent_error(ev: Event):
    print(f'[{ev.source:<10}  {"agent:error":>12}] {ev.data.get("error","")}')


_LOG_HANDLERS = {
    'client': [
        ('lifecycle:client:start', _on_client_start),
        ('lifecycle:client:error', _on_client_error),
        ('lifecycle:client:retry', _on_client_retry),
        ('lifecycle:client:end', _on_client_end),
        ('lifecycle:client:tokens', _on_client_tokens),
    ],
    'tool': [
        ('lifecycle:tool:start', _on_tool_start),
        ('lifecycle:tool:step', _on_tool_step),
        ('lifecycle:tool:end', _on_tool_end),
        ('lifecycle:tool:error', _on_tool_error),
    ],
    'agent': [
        ('lifecycle:agent:start', _on_agent_start),
        ('lifecycle:agent:step', _on_agent_step),
        ('lifecycle:agent:end', _on_agent_end),
        ('lifecycle:agent:error', _on_agent_error),
        ('lifecycle:agent:tokens', _on_agent_tokens),
    ],
    'team': [
        ('lifecycle:team:start', _on_agent_start),
        ('lifecycle:team:step', _on_agent_step),
        ('lifecycle:team:end', _on_agent_end),
        ('lifecycle:team:error', _on_agent_error),
        ('lifecycle:team:tokens', _on_team_tokens),
    ],
}


def subscribe_logging(runtime, categories):
    if not categories:
        categories = ('client', 'tool', 'agent')
    for cat in categories:
        if cat in runtime._logging_enabled:
            continue
        runtime._logging_enabled.add(cat)
        for pattern, handler in _LOG_HANDLERS.get(cat, []):
            runtime.subscribe(pattern, handler)
