from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass, field

from chatchat.core.sanitization import sanitize_unicode

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




class FileMailbox(Mailbox):

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        lock = self.path.with_suffix(self.path.suffix + '.lock')
        fd = None
        for _ in range(50):
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                time.sleep(0.02)
        acquired = fd is not None
        try:
            yield
        finally:
            if acquired:
                os.close(fd)
                try:
                    os.unlink(lock)
                except OSError:
                    pass

    @staticmethod
    def _record(m: Message) -> dict:
        return {'from_': m.from_, 'text': m.text, 'timestamp': m.timestamp,
                'read': m.read, 'color': m.color, 'summary': m.summary,
                'type': m.type}

    def _read_file(self) -> list[Message]:
        try:
            records = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        return [Message(from_=r.get('from_', ''), text=r.get('text', ''),
                        timestamp=r.get('timestamp', 0), read=r.get('read', False),
                        color=r.get('color', ''), summary=r.get('summary', ''),
                        type=r.get('type', 'text'))
                for r in (records if isinstance(records, list) else [])
                if isinstance(r, dict)]

    def _write_file(self, messages: list[Message]):
        self.path.write_text(json.dumps([self._record(m) for m in messages],
                                        ensure_ascii=False), encoding='utf-8')

    def write(self, from_, text: str, *, type: str = 'text', color: str = '',
              summary: str = '') -> None:
        with self._locked():
            msgs = self._read_file()
            msgs.append(Message(from_=from_, text=text, type=type,
                                color=color, summary=summary))
            self._write_file(msgs)

    def unread(self) -> list[Message]:
        return [m for m in self._read_file() if not m.read]

    def all(self) -> list[Message]:
        return self._read_file()

    def mark_all_read(self) -> None:
        with self._locked():
            msgs = self._read_file()
            for m in msgs:
                m.read = True
            self._write_file(msgs)

    def mark_read(self, msg: Message) -> None:
        with self._locked():
            msgs = self._read_file()
            for m in msgs:
                if (m.from_, m.text, m.timestamp) == (msg.from_, msg.text,
                                                      msg.timestamp):
                    m.read = True
            self._write_file(msgs)

    def clear(self) -> None:
        with self._locked():
            self._write_file([])

    def __len__(self) -> int:
        return len(self._read_file())

    def __iter__(self):
        return iter(self._read_file())


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
        f'<teammate-message teammate_id="{m.from_}">\n'
        f'{sanitize_unicode(m.text)}\n</teammate-message>'
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
