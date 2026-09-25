from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

TASK_STATUSES = ('pending', 'in_progress', 'completed')

HIGH_WATER_MARK = '.highwatermark'
LOCK_SUFFIX = '.lock'
LOCK_TRIES = 50
LOCK_WAIT = 0.02

_UNSAFE = re.compile(r'[^A-Za-z0-9_-]')


def safe_component(value) -> str:
    return _UNSAFE.sub('-', str(value))


@dataclass
class TaskItem:
    id: str
    subject: str
    description: str
    status: str = 'pending'
    active_form: str = ''
    owner: str = ''
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict) -> 'TaskItem':
        return TaskItem(id=str(data.get('id', '')),
                    subject=data.get('subject', '') or '',
                    description=data.get('description', '') or '',
                    status=data.get('status') if data.get('status') in TASK_STATUSES else 'pending',
                    active_form=data.get('active_form', '') or '',
                    owner=data.get('owner', '') or '',
                    blocks=[str(b) for b in data.get('blocks', []) or []],
                    blocked_by=[str(b) for b in data.get('blocked_by', []) or []],
                    metadata=dict(data.get('metadata') or {}))

    def open(self) -> bool:
        return self.status != 'completed'


def work_prompt(task: TaskItem) -> str:
    body = f'Work on task #{task.id}: {task.subject}.'
    return f'{body}\n\n{task.description}' if task.description else body


@dataclass
class Claim:
    ok: bool
    reason: str = ''
    task: TaskItem | None = None
    busy_with: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


class TaskList:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id) -> Path:
        return self.directory / f'{safe_component(task_id)}.json'

    @contextmanager
    def _locked(self, path: Path):
        lock = path.with_name(path.name + LOCK_SUFFIX)
        fd = None
        for _ in range(LOCK_TRIES):
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                time.sleep(LOCK_WAIT)
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

    def _read(self, task_id) -> TaskItem | None:
        path = self._path(task_id)
        if str(task_id) != safe_component(task_id) or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return TaskItem.from_dict(data) if isinstance(data, dict) else None

    def _write(self, task: TaskItem) -> TaskItem:
        self._path(task.id).write_text(
            json.dumps(asdict(task), ensure_ascii=False, indent=2),
            encoding='utf-8')
        return task

    def _highest(self) -> int:
        highest = 0
        for path in self.directory.glob('*.json'):
            try:
                highest = max(highest, int(path.stem))
            except ValueError:
                continue
        try:
            highest = max(highest, int(self.directory.joinpath(HIGH_WATER_MARK)
                                       .read_text().strip()))
        except (OSError, ValueError):
            pass
        return highest

    def create(self, subject: str, description: str, *,
               active_form: str = '',
               metadata: dict | None = None) -> TaskItem:
        with self._locked(self.directory / 'ids'):
            task = TaskItem(id=str(self._highest() + 1), subject=subject,
                        description=description, active_form=active_form,
                        metadata=dict(metadata or {}))
            return self._write(task)

    def get(self, task_id) -> TaskItem | None:
        return self._read(task_id)

    def available(self) -> TaskItem | None:
        tasks = self.all()
        unresolved = {t.id for t in tasks if t.open()}
        for task in tasks:
            if task.status != 'pending' or task.owner:
                continue
            if not any(b in unresolved for b in task.blocked_by):
                return task
        return None

    def all(self) -> list[TaskItem]:
        found = []
        for path in sorted(self.directory.glob('*.json'),
                           key=lambda p: (len(p.stem), p.stem)):
            task = self._read(path.stem)
            if task is not None:
                found.append(task)
        return found

    def update(self, task_id, **fields) -> TaskItem | None:
        if 'status' in fields and fields['status'] not in TASK_STATUSES:
            return None
        with self._locked(self._path(task_id)):
            task = self._read(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if key == 'id' or key not in TaskItem.__dataclass_fields__:
                    continue
                if key in ('blocks', 'blocked_by'):
                    value = [str(v) for v in value or []]
                if key == 'metadata':
                    merged = dict(task.metadata)
                    for name, item in dict(value or {}).items():
                        if item is None:
                            merged.pop(name, None)
                        else:
                            merged[name] = item
                    value = merged
                setattr(task, key, value)
            return self._write(task)

    def delete(self, task_id) -> bool:
        with self._locked(self._path(task_id)):
            task = self._read(task_id)
            if task is None:
                return False
            try:
                number = int(task_id)
            except ValueError:
                number = 0
            mark = self.directory / HIGH_WATER_MARK
            current = 0
            try:
                current = int(mark.read_text().strip())
            except (OSError, ValueError):
                pass
            if number > current:
                mark.write_text(str(number), encoding='utf-8')
            self._path(task_id).unlink()
        for other in self.all():
            blocks = [b for b in other.blocks if b != str(task_id)]
            blocked_by = [b for b in other.blocked_by if b != str(task_id)]
            if blocks != other.blocks or blocked_by != other.blocked_by:
                self.update(other.id, blocks=blocks, blocked_by=blocked_by)
        return True

    def block(self, blocker_id, blocked_id) -> bool:
        blocker = self._read(blocker_id)
        blocked = self._read(blocked_id)
        if blocker is None or blocked is None:
            return False
        if str(blocked_id) not in blocker.blocks:
            self.update(blocker_id, blocks=[*blocker.blocks, str(blocked_id)])
        if str(blocker_id) not in blocked.blocked_by:
            self.update(blocked_id,
                        blocked_by=[*blocked.blocked_by, str(blocker_id)])
        return True

    def _claim(self, task_id, agent_id, all_tasks, check_agent_busy) -> Claim:
        task = next((t for t in all_tasks if t.id == str(task_id)), None)
        if task is None:
            return Claim(ok=False, reason='task_not_found')
        if task.owner and task.owner != agent_id:
            return Claim(ok=False, reason='already_claimed', task=task)
        if not task.open():
            return Claim(ok=False, reason='already_resolved', task=task)
        unresolved = {t.id for t in all_tasks if t.open()}
        blockers = [b for b in task.blocked_by if b in unresolved]
        if blockers:
            return Claim(ok=False, reason='blocked', task=task,
                         blocked_by=blockers)
        if check_agent_busy:
            busy = [t.id for t in all_tasks
                    if t.open() and t.owner == agent_id and t.id != task.id]
            if busy:
                return Claim(ok=False, reason='agent_busy', task=task,
                             busy_with=busy)
        return Claim(ok=True, task=self.update(task_id, owner=agent_id))

    def claim(self, task_id, agent_id, *,
              check_agent_busy: bool = False) -> Claim:
        if check_agent_busy:
            with self._locked(self.directory / 'ids'):
                return self._claim(task_id, agent_id, self.all(), True)
        with self._locked(self._path(task_id)):
            return self._claim(task_id, agent_id, self.all(), False)

    def unassign(self, agent_id, agent_name: str = '') -> list[TaskItem]:
        released = []
        for task in self.all():
            if task.open() and task.owner in (agent_id, agent_name):
                self.update(task.id, owner='', status='pending')
                released.append(task)
        return released

    def current_of(self, agent_id, agent_name: str = '') -> list[TaskItem]:
        return [task for task in self.all()
                if task.open() and task.owner in (agent_id, agent_name)]
