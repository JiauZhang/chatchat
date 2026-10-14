import json

from chatchat.protocols import Delta, ToolCall


def endpoint(base_url):
    return base_url.rstrip('/') + '/chat/completions'


def headers(api_key):
    return {'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'}


def to_openai(messages):
    out = []
    for m in messages:
        c = m.get('content')
        if isinstance(c, list) and c:
            if m.get('role') == 'assistant':
                calls = [{'id': t.get('id'), 'type': 'function',
                          'function': {'name': t.get('name'),
                                       'arguments': json.dumps(t.get('input', {}))}}
                         for t in c if t.get('type') == 'tool_use']
                out.append({'role': 'assistant', 'content': None, 'tool_calls': calls})
            else:
                out += [{'role': 'tool', 'tool_call_id': t.get('tool_use_id'),
                         'content': t.get('content', '')} for t in c]
        else:
            out.append({'role': m.get('role', 'user'), 'content': c or ''})
    return out


def to_openai_tools(schemas):
    return [{'type': 'function', 'function': {
        'name': s['name'],
        'description': s.get('description', ''),
        'parameters': s.get('input_schema', {}),
    }} for s in schemas]


def payload(messages, tools, model, thinking):
    body = {'model': model, 'messages': to_openai(messages), 'stream': True,
            'stream_options': {'include_usage': True}}
    body.update(thinking.request())
    if tools:
        body['tools'] = to_openai_tools(tools)
    return body


def parse(line):
    line = line.strip()
    if not line or line == b'[DONE]':
        return None, []
    if line.startswith(b'data:'):
        line = line[5:].strip()
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None, []
    deltas = []
    for ch in data.get('choices') or []:
        d = ch.get('delta', {})
        tcs = [ToolCall(index=tc.get('index', 0), id=tc.get('id') or '',
                        name=(tc.get('function') or {}).get('name') or '',
                        arguments=(tc.get('function') or {}).get('arguments') or '')
               for tc in d.get('tool_calls') or []]
        deltas.append(Delta(role=d.get('role') or '', content=d.get('content') or '',
                            reasoning_content=d.get('reasoning_content') or '',
                            tool_calls=tcs))
    return data.get('usage'), deltas
