from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from chatchat.tasks.cron import human, next_run, parse


TASKS_FILE = 'scheduled_tasks.json'

LOCK_FILE = 'scheduled_tasks.lock'


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _stamp(value: datetime) -> str:
    return value.replace(second=0, microsecond=0).isoformat()


def _moment(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


@dataclass
class Jitter:
    recurring_frac: float = 0.1
    recurring_cap: float = 15 * 60.0
    one_shot_max: float = 90.0
    one_shot_floor: float = 0.0
    one_shot_minute_mod: int = 30
    recurring_max_age: float = 7 * 24 * 60 * 60.0


DEFAULT_JITTER = Jitter()


def _fraction(task_id: str) -> float:
    try:
        return int(str(task_id)[:8], 16) / 0x1_0000_0000
    except ValueError:
        return 0.0


def _anchor(task: dict) -> datetime | None:
    return (_moment(task.get('last_fired_at'))
            or _moment(task.get('created_at')))


def next_fire(task: dict, now: datetime | None = None,
              cfg: Jitter = DEFAULT_JITTER) -> datetime | None:
    now = now or _now()
    fields = parse(task.get('cron') or '')
    if fields is None:
        return None
    anchor = _anchor(task) or now
    first = next_run(fields, anchor)
    if first is None:
        return None
    return _lead(one_shot=not task.get('recurring'), task=task, first=first,
                 now=now, fields=fields, cfg=cfg)


def _lead(*, one_shot: bool, task: dict, first: datetime, now: datetime,
          fields: dict, cfg: Jitter) -> datetime:
    fraction = _fraction(task.get('id') or '')
    if one_shot:
        if cfg.one_shot_minute_mod and first.minute % cfg.one_shot_minute_mod:
            return first
        lead = cfg.one_shot_floor + fraction * (cfg.one_shot_max
                                                - cfg.one_shot_floor)
        return max(first - timedelta(seconds=lead), now)
    following = next_run(fields, first)
    if following is None:
        return first
    spread = min(fraction * cfg.recurring_frac
                 * (following - first).total_seconds(), cfg.recurring_cap)
    return first + timedelta(seconds=spread)


def expired(task: dict, now: datetime | None = None,
            cfg: Jitter = DEFAULT_JITTER) -> bool:
    if not task.get('recurring') or task.get('permanent'):
        return False
    created = _moment(task.get('created_at'))
    if created is None:
        return False
    return (now or _now()) - created > timedelta(seconds=cfg.recurring_max_age)


def find_missed(tasks: list[dict], now: datetime) -> list[dict]:
    missed = []
    for task in tasks:
        fields = parse(task.get('cron') or '')
        created = _moment(task.get('created_at'))
        if fields is None or created is None:
            continue
        following = next_run(fields, created)
        if following is not None and following < now:
            missed.append(task)
    return missed


class CronStore:

    MAX_JOBS = 50

    def __init__(self, directory):
        self.directory = Path(directory)
        self.refused = ''
        self._session: list[dict] = []

    @property
    def path(self) -> Path:
        return self.directory / TASKS_FILE

    def durable(self) -> list[dict]:
        try:
            body = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        tasks = body.get('tasks') if isinstance(body, dict) else None
        out = []
        for item in tasks or []:
            if not isinstance(item, dict):
                continue
            if not all(str(item.get(key) or '') for key in
                       ('id', 'cron', 'prompt', 'created_at')):
                continue
            if parse(item['cron']) is None:
                continue
            out.append(dict(item))
        return out

    def session(self) -> list[dict]:
        return [dict(task) for task in self._session]

    def all(self) -> list[dict]:
        return self.durable() + self.session()

    def _write(self, tasks: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        body = {'tasks': [{key: value for key, value in task.items()
                           if key != 'durable'} for task in tasks]}
        self.path.write_text(json.dumps(body, indent=2, ensure_ascii=False)
                             + '\n', encoding='utf-8')

    def add(self, cron: str, prompt: str, *, recurring: bool = True,
            durable: bool = False, agent: str = '') -> dict | None:
        self.refused = ''
        if parse(cron) is None:
            self.refused = f'invalid cron expression: {cron}'
            return None
        if next_run(parse(cron), _now()) is None:
            self.refused = f'{cron} matches no date in the next year'
            return None
        if len(self.all()) >= self.MAX_JOBS:
            self.refused = f'too many scheduled jobs (max {self.MAX_JOBS})'
            return None
        task = {'id': uuid.uuid4().hex[:8], 'cron': cron, 'prompt': prompt,
                'created_at': _stamp(_now()), 'recurring': recurring}
        if agent:
            task['agent'] = agent
        if durable:
            self._write(self.durable() + [task])
        else:
            self._session.append(task)
            task['durable'] = False
        return dict(task)

    def remove(self, task_id: str) -> dict | None:
        found = next((task for task in self.all()
                      if task.get('id') == task_id), None)
        if found is None:
            return None
        if found.get('durable') is False or any(
                task.get('id') == task_id for task in self._session):
            self._session = [task for task in self._session
                             if task.get('id') != task_id]
            return found
        self._write([task for task in self.durable()
                     if task.get('id') != task_id])
        return found

    def mark_fired(self, task_id: str, when: datetime) -> None:
        stored = _stamp(when)
        for task in self._session:
            if task.get('id') == task_id:
                task['last_fired_at'] = stored
        held = self.durable()
        if any(task.get('id') == task_id for task in held):
            self._write([{**task, 'last_fired_at': stored}
                         if task.get('id') == task_id else task
                         for task in held])

    def due(self, now: datetime | None = None,
            cfg: Jitter = DEFAULT_JITTER) -> list[dict]:
        now = now or _now()
        due = []
        for task in self.all():
            if expired(task, now, cfg):
                continue
            when = next_fire(task, now, cfg)
            if when is not None and when <= now:
                due.append(task)
        return due


class SchedulerLock:

    def __init__(self, directory, session_id: str):
        self.directory = Path(directory)
        self.session_id = session_id

    @property
    def path(self) -> Path:
        return self.directory / LOCK_FILE

    def held_by(self) -> dict | None:
        try:
            body = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return body if isinstance(body, dict) and body.get('pid') else None

    def _living(self, owner: dict) -> bool:
        pid = owner.get('pid')
        if not isinstance(pid, int):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    def acquire(self) -> bool:
        owner = self.held_by()
        if owner is not None:
            if owner.get('session_id') == self.session_id:
                return True
            if self._living(owner):
                return False
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({'pid': os.getpid(), 'session_id': self.session_id}),
            encoding='utf-8')
        return True

    def owns(self) -> bool:
        owner = self.held_by()
        return bool(owner) and owner.get('session_id') == self.session_id

    def release(self) -> None:
        if self.owns():
            self.path.unlink(missing_ok=True)


def describe(task: dict) -> str:
    where = ('written to disk, so it survives a restart'
             if task.get('durable') is not False
             else 'kept in this session only')
    kind = ('repeats' if task.get('recurring')
            else 'fires once and then goes away')
    return (f'{task["id"]}: {human(task["cron"])} - {task["prompt"][:60]} '
            f'({kind}, {where})')
