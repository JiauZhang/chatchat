from dataclasses import dataclass, field


@dataclass
class ToolCall:
    index: int = 0
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class Delta:
    role: str = ""
    content: str = ""
    tool_calls: list = field(default_factory=list)
    reasoning_content: str = ""


from chatchat.protocols import anthropic, openai  # noqa: E402

BUILTIN = {"openai": openai, "anthropic": anthropic}


def get_protocol(protocol_type, protocols=None):
    table = BUILTIN if protocols is None else {**BUILTIN, **(protocols or {})}
    try:
        return table[protocol_type]
    except KeyError:
        raise ValueError(f"protocol type must be one of {sorted(table)}, not {protocol_type!r}") from None
