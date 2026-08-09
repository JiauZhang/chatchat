from __future__ import annotations
import random
import string
from dataclasses import dataclass, field
from typing import Any


def make_id():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


@dataclass
class Message:
    id: str = field(default_factory=lambda: make_id() + make_id())
    sender: str | None = None
    recipient: str | None = None
    type: str = 'text'
    subtype: str = ''
    payload: Any = None
    reply_to: str | None = None