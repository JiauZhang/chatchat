from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass(frozen=True)
class ID:
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: str = 'worker'
    name: str = ''

    def __str__(self):
        return f'{self.kind}:{self.name or self.uid}'


@dataclass
class Message:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sender: ID | None = None
    recipient: ID | None = None
    type: str = 'text'
    subtype: str = ''
    payload: Any = None
    reply_to: str | None = None