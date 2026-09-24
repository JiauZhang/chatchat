from __future__ import annotations

import json

CHARS_PER_TOKEN = 4


def measured(usage: dict) -> int:
    return (int(usage.get('prompt_tokens') or 0)
            + int(usage.get('completion_tokens') or 0))


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return '' if content is None else str(content)
    out = []
    for block in content:
        if not isinstance(block, dict):
            out.append(_text_of(block))
            continue
        kind = block.get('type')
        if kind == 'tool_use':
            out.append(json.dumps({'name': block.get('name') or '',
                                   'input': block.get('input') or {}},
                                  ensure_ascii=False))
        elif kind == 'tool_result':
            out.append(_text_of(block.get('content')))
        else:
            out.append(_text_of(block.get('text')))
    return '\n'.join(part for part in out if part)


def rough(message: dict) -> int:
    return len(_text_of(message.get('content'))) // CHARS_PER_TOKEN


def context_estimate(messages: list[dict]) -> int:
    """How full the window is, for the compaction trigger: what the API last
    measured plus a character count of everything appended since."""
    for index in range(len(messages) - 1, -1, -1):
        usage = messages[index].get('usage')
        if isinstance(usage, dict) and 'prompt_tokens' in usage:
            return (measured(usage)
                    + sum(rough(message) for message in messages[index + 1:]))
    return sum(rough(message) for message in messages)
