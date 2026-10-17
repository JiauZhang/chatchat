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

PROTOCOLS = {"openai": openai, "anthropic": anthropic}


def get_protocol(protocol_type):
    try:
        return PROTOCOLS[protocol_type]
    except KeyError:
        raise ValueError(f"protocol type must be one of {sorted(PROTOCOLS)}, not {protocol_type!r}") from None
