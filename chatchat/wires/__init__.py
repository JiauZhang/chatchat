from dataclasses import dataclass, field


@dataclass
class ToolCall:
    index: int = 0
    id: str = ''
    name: str = ''
    arguments: str = ''


@dataclass
class Delta:
    role: str = ''
    content: str = ''
    tool_calls: list = field(default_factory=list)
    reasoning_content: str = ''


from chatchat.wires import anthropic, openai  # noqa: E402
from chatchat.wires.openai import to_openai, to_openai_tools  # noqa: E402,F401

WIRES = {'openai': openai, 'anthropic': anthropic}


def get_wire(wire_type):
    try:
        return WIRES[wire_type]
    except KeyError:
        raise ValueError(f'wire type must be one of {sorted(WIRES)}, '
                         f'not {wire_type!r}') from None
