import json

from chatchat.protocols import Delta, ToolCall


def endpoint(base_url):
    return base_url.rstrip("/") + "/responses"


def headers(api_key):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _image_part(block):
    source = block.get("source") or {}
    media = source.get("media_type") or "image/png"
    return {"type": "input_image", "image_url": f"data:{media};base64,{source.get('data', '')}"}


def _input_text(text):
    return {"type": "input_text", "text": text or ""}


def _parts(blocks):
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "image":
            parts.append(_image_part(b))
        elif b.get("type") == "text":
            parts.append(_input_text(b.get("text")))
    return parts


def _tool_output(content):
    if not isinstance(content, list):
        return content or ""
    return _parts(content)


def input_items(messages):
    items = []
    for m in messages:
        role = m.get("role")
        c = m.get("content")
        if role == "system":
            continue
        if role == "assistant":
            replay = m.get("response_items")
            if replay:
                items += [dict(item) for item in replay]
            elif isinstance(c, list):
                items += [
                    {
                        "type": "function_call",
                        "id": f"fc_{b.get('id')}",
                        "call_id": b.get("id"),
                        "name": b.get("name"),
                        "arguments": json.dumps(b.get("input", {})),
                    }
                    for b in c
                    if b.get("type") == "tool_use"
                ]
            elif c:
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": c}]})
            continue
        if isinstance(c, list):
            has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if has_result:
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        items.append(
                            {
                                "type": "function_call_output",
                                "call_id": b.get("tool_use_id"),
                                "output": _tool_output(b.get("content")),
                            }
                        )
                    elif b.get("type") == "text":
                        items.append({"role": "user", "content": [_input_text(b.get("text"))]})
            else:
                parts = _parts(c)
                if parts:
                    items.append({"role": "user", "content": parts})
            continue
        items.append({"role": role or "user", "content": c or ""})
    return items


def payload(messages, tools, model, thinking, chain=None):
    system = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    body = {
        "model": model,
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "input": input_items(messages),
    }
    if system:
        body["instructions"] = "\n\n".join(system)
    native = (thinking.native or {}).get("openai")
    if native is not None:
        body.update(native)
    elif thinking.enabled:
        body["reasoning"] = {"effort": thinking.level}
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s.get("input_schema", {}),
            }
            for s in tools
        ]
    return body


def _usage(u):
    usage = {
        "prompt_tokens": u.get("input_tokens", 0),
        "completion_tokens": u.get("output_tokens", 0),
        "total_tokens": u.get("total_tokens") or (u.get("input_tokens", 0) + u.get("output_tokens", 0)),
    }
    details = u.get("input_tokens_details") or {}
    if details.get("cached_tokens"):
        usage["prompt_tokens_details"] = {"cached_tokens": details["cached_tokens"]}
    return usage


def parse(line):
    line = line.strip()
    if not line.startswith(b"data:"):
        return None, [], None
    try:
        data = json.loads(line[5:].strip())
    except json.JSONDecodeError:
        return None, [], None
    kind = data.get("type")
    if kind == "response.output_text.delta":
        return None, [Delta(content=data.get("delta") or "")], None
    if kind in ("response.reasoning_text.delta", "response.reasoning_summary_text.delta"):
        return None, [Delta(reasoning_content=data.get("delta") or "")], None
    if kind == "response.output_item.added":
        item = data.get("item") or {}
        if item.get("type") == "function_call":
            tc = ToolCall(index=data.get("output_index", 0), id=item.get("call_id") or "", name=item.get("name") or "")
            return None, [Delta(tool_calls=[tc])], None
        if item.get("type") == "reasoning":
            return None, [], None
        return None, [], None
    if kind == "response.function_call_arguments.delta":
        tc = ToolCall(index=data.get("output_index", 0), arguments=data.get("delta") or "")
        return None, [Delta(tool_calls=[tc])], None
    if kind == "response.completed":
        response = data.get("response") or {}
        return _usage(response.get("usage") or {}), [], response
    return None, [], None
