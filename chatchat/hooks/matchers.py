import fnmatch
import json
import re

_IF_CONDITION_RE = re.compile(r'^(\w+)\((.*)\)$')


def matches_pattern(match_query: str, matcher: str) -> bool:
    if not matcher or matcher == '*':
        return True
    if re.fullmatch(r'[a-zA-Z0-9_|]+', matcher):
        return match_query in matcher.split('|')
    try:
        return re.search(matcher, match_query) is not None
    except re.error:
        return False


def parse_if_condition(if_str: str):
    m = _IF_CONDITION_RE.fullmatch(if_str)
    if m is None:
        return None
    return m.group(1), m.group(2)


def if_matches(if_str: str, tool_name: str, tool_input: dict) -> bool:
    parsed = parse_if_condition(if_str)
    if parsed is None:
        return matches_pattern(tool_name, if_str)
    tool_glob, rule = parsed
    if tool_glob != tool_name:
        return False
    if not rule:
        return True
    values = [v for v in (tool_input or {}).values() if isinstance(v, str)]
    return any(fnmatch.fnmatch(v, rule) for v in values)


def if_condition_applies(hook_event: str) -> bool:
    return hook_event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure')
