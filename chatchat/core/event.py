import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    topic: str = ''
    source: str = ''
    data: Any = None
    reply_to: str = ''
    expect_reply: bool = False
    type: str = ''
    subtype: str = ''
    timestamp: float = field(default_factory=time.time)


def parse_topic(topic: str) -> tuple[str, str, str, str]:
    kind = eid = msg_type = subtype = ''
    parts = topic.split(':')
    if len(parts) >= 4 and parts[0] == 'entity':
        kind, eid, msg_type = parts[1], parts[2], parts[3]
        if len(parts) >= 5:
            subtype = parts[4]
    return kind, eid, msg_type, subtype


def annotate(event: Event):
    _, _, event.type, event.subtype = parse_topic(event.topic)
