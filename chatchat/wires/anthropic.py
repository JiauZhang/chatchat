import json

from chatchat.wires import Delta, ToolCall

VERSION = '2023-06-01'


def endpoint(base_url):
    return base_url.rstrip('/') + '/v1/messages'


def headers(api_key):
    return {'x-api-key': api_key, 'anthropic-version': VERSION,
            'Content-Type': 'application/json'}


def payload(messages, tools, model, thinking, max_tokens=8192):
    system = [m['content'] for m in messages
              if m.get('role') == 'system' and m.get('content')]
    body = {'model': model, 'max_tokens': max_tokens, 'stream': True,
            'messages': [{'role': m.get('role', 'user'),
                          'content': m.get('content') or ''}
                         for m in messages if m.get('role') != 'system']}
    if system:
        body['system'] = '\n\n'.join(system)
    body.update(thinking.request())
    if tools:
        body['tools'] = [{'name': s['name'],
                          'description': s.get('description', ''),
                          'input_schema': s.get('input_schema', {})}
                         for s in tools]
    return body


def _usage(u):
    usage = {'prompt_tokens': u.get('input_tokens', 0),
             'completion_tokens': u.get('output_tokens', 0),
             'total_tokens': u.get('input_tokens', 0)
                             + u.get('output_tokens', 0)}
    if u.get('cache_read_input_tokens'):
        usage['prompt_tokens_details'] = {
            'cached_tokens': u['cache_read_input_tokens']}
    return usage


def parse(line):
    line = line.strip()
    if not line.startswith(b'data:'):
        return None, []
    try:
        data = json.loads(line[5:].strip())
    except json.JSONDecodeError:
        return None, []
    kind = data.get('type')
    if kind == 'message_start':
        return _usage((data.get('message') or {}).get('usage') or {}), []
    if kind == 'message_delta':
        u = data.get('usage') or {}
        return {'completion_tokens': u.get('output_tokens', 0),
                'total_tokens': u.get('output_tokens', 0)}, []
    if kind == 'content_block_start':
        block = data.get('content_block') or {}
        if block.get('type') != 'tool_use':
            return None, []
        return None, [Delta(tool_calls=[ToolCall(index=data.get('index', 0),
                                                 id=block.get('id') or '',
                                                 name=block.get('name') or '')])]
    if kind == 'content_block_delta':
        delta = data.get('delta') or {}
        dtype = delta.get('type')
        if dtype == 'text_delta':
            return None, [Delta(content=delta.get('text') or '')]
        if dtype == 'thinking_delta':
            return None, [Delta(reasoning_content=delta.get('thinking') or '')]
        if dtype == 'input_json_delta':
            return None, [Delta(tool_calls=[ToolCall(index=data.get('index', 0),
                                                     arguments=delta.get('partial_json') or '')])]
    return None, []
