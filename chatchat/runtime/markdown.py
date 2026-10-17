from __future__ import annotations

import re

import yaml

_FRONTMATTER = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n?")
_KEY_VALUE = re.compile(r"^([a-zA-Z_-]+):\s+(.+)$")
_QUOTED = ('"', "'")
_YAML_SPECIAL = re.compile(r"""[{}[\]*&#!|>%@`]|: """)
# PyYAML speaks YAML 1.1, where 12:34 is a sexagesimal 754; quote such values
# so they arrive as the strings their author wrote.
_SEXAGESIMAL = re.compile(r"^\d+(:\d+)+$")


def _has_bare_sexagesimal(block: str) -> bool:
    for line in block.splitlines():
        match = _KEY_VALUE.match(line)
        if match is not None and _SEXAGESIMAL.match(match.group(2)):
            return True
    return False


def _quote_problematic_values(block: str) -> str:
    """Quote unquoted values that YAML would reject or mangle, so a hand-written
    glob like **/*.{ts,tsx} or a description carrying ': ' still parses. A bare
    colon without a following space stays unquoted: 12:34 and https:// are
    valid plain scalars."""
    lines = []
    for line in block.splitlines():
        match = _KEY_VALUE.match(line)
        if match is not None:
            value = match.group(2)
            already_quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTED
            if not already_quoted and (_YAML_SPECIAL.search(value) or _SEXAGESIMAL.match(value)):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{match.group(1)}: "{escaped}"')
                continue
        lines.append(line)
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """(meta, body). meta is None when the block is not valid YAML even after
    quoting repair — the caller reports the file as broken rather than
    re-reading it with a looser parser that would hide the mistake. When the
    block carries bare 12:34-style values, the quoted reading wins: PyYAML
    speaks YAML 1.1 and would silently turn them into sexagesimal ints."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    block, body = match.group(1), text[match.end() :].strip()
    repaired = _quote_problematic_values(block)
    order = (repaired, block) if _has_bare_sexagesimal(block) else (block, repaired)
    for candidate in order:
        try:
            meta = yaml.safe_load(candidate)
        except yaml.YAMLError:
            continue
        if isinstance(meta, dict):
            return meta, body
    return None, body
