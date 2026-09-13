from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

STRUCTURED_TYPES = (
    'idle_notification', 'permission_request', 'permission_response',
    'sandbox_permission_request', 'sandbox_permission_response',
    'shutdown_request', 'shutdown_approved', 'shutdown_rejected',
    'team_permission_update', 'mode_set_request', 'plan_approval_request',
    'plan_approval_response', 'task_assignment',
)

IDLE_REASONS = ('available', 'interrupted', 'failed')
TASK_STATUSES = ('resolved', 'blocked', 'failed')


@dataclass
class Message:
    from_: str
    text: str
    timestamp: float = field(default_factory=time.time)
    read: bool = False
    color: str = ''
    summary: str = ''
    type: str = 'text'

    @property
    def from_name(self) -> str:
        return self.from_

    def structured(self) -> dict | None:
        return parse_protocol(self.text)


@dataclass
class Mailbox:
    _messages: list[Message] = field(default_factory=list)

    def write(self, from_, text: str, *, type: str = 'text', color: str = '',
              summary: str = '') -> None:
        self._messages.append(Message(from_=from_, text=text, type=type,
                                      color=color, summary=summary))

    def unread(self) -> list[Message]:
        return [m for m in self._messages if not m.read]

    def all(self) -> list[Message]:
        return self._messages

    def mark_all_read(self) -> None:
        for m in self._messages:
            m.read = True

    def mark_read(self, msg: Message) -> None:
        msg.read = True

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)


def is_structured_protocol_message(text: str) -> str | None:
    parsed = parse_protocol(text)
    if parsed is None:
        return None
    t = parsed.get('type')
    return t if t in STRUCTURED_TYPES else None


def parse_protocol(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) and 'type' in obj else None


def format_teammate_batch(unread: list[Message]) -> str:
    return '\n\n'.join(
        f'<teammate_message teammate_id="{m.from_}">{m.text}</teammate_message>'
        for m in unread)


def idle_notification(from_, *, idle_reason='available', summary='',
                      completed_task_id='', completed_status='',
                      failure_reason='') -> str:
    return json.dumps({
        'type': 'idle_notification', 'from': from_,
        'timestamp': time.time(), 'idle_reason': idle_reason,
        'summary': summary, 'completed_task_id': completed_task_id,
        'completed_status': completed_status, 'failure_reason': failure_reason,
    }, ensure_ascii=False)


def task_assignment(task_id, subject, description, assigned_by) -> str:
    return json.dumps({
        'type': 'task_assignment', 'task_id': task_id, 'subject': subject,
        'description': description, 'assigned_by': assigned_by,
        'timestamp': time.time(),
    }, ensure_ascii=False)


def shutdown_request(request_id, from_, reason='') -> str:
    return json.dumps({'type': 'shutdown_request', 'request_id': request_id,
                       'from': from_, 'reason': reason,
                       'timestamp': time.time()}, ensure_ascii=False)


def shutdown_approved(request_id, from_) -> str:
    return json.dumps({'type': 'shutdown_approved', 'request_id': request_id,
                       'from': from_, 'timestamp': time.time()},
                      ensure_ascii=False)


def shutdown_rejected(request_id, from_, reason) -> str:
    return json.dumps({'type': 'shutdown_rejected', 'request_id': request_id,
                       'from': from_, 'reason': reason,
                       'timestamp': time.time()}, ensure_ascii=False)
