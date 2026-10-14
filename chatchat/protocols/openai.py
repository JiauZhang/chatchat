import json

from chatchat.protocols import Delta, ToolCall


def endpoint(base_url):
    return base_url.rstrip('/') + '/chat/completions'


def headers(api_key):
    return {'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'}


def _image_part(block):
    source = block.get('source') or {}
    media = source.get('media_type') or 'image/png'
    return {'type': 'image_url',
            'image_url': {'url': f'data:{media};base64,{source.get("data", "")}'}}


def _user_parts(blocks):
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get('type') == 'image':
            parts.append(_image_part(b))
        elif b.get('type') == 'text':
            parts.append({'type': 'text', 'text': b.get('text') or ''})
    return parts


def _split_tool_result(block):
    content = block.get('content')
    if not isinstance(content, list):
        return content or '', []
    text = '\n'.join(x.get('text') or '' for x in content
                     if isinstance(x, dict) and x.get('type') == 'text')
    images = [x for x in content
              if isinstance(x, dict) and x.get('type') == 'image']
    return text, images


def to_openai(messages):
    out = []
    for m in messages:
        role = m.get('role', 'user')
        c = m.get('content')
        if isinstance(c, list) and c:
            if role == 'assistant':
                calls = [{'id': t.get('id'), 'type': 'function',
                          'function': {'name': t.get('name'),
                                       'arguments': json.dumps(t.get('input', {}))}}
                         for t in c if t.get('type') == 'tool_use']
                out.append({'role': 'assistant', 'content': None, 'tool_calls': calls})
            elif not any(isinstance(b, dict) and b.get('type') == 'tool_result'
                         for b in c):
                out.append({'role': role, 'content': _user_parts(c)})
            else:
                images = []
                for t in c:
                    if isinstance(t, dict) and t.get('type') == 'tool_result':
                        text, found = _split_tool_result(t)
                        images += found
                    else:
                        text = t.get('content', '')
                    out.append({'role': 'tool',
                                'tool_call_id': t.get('tool_use_id'),
                                'content': text})
                if images:
                    out.append({'role': 'user',
                                'content': [_image_part(b) for b in images]})
        else:
            out.append({'role': role, 'content': c or ''})
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
