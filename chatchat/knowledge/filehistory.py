from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


MAX_SNAPSHOTS = 100
STATE_FILE = 'state.json'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class Backup:
    name: str | None
    version: int


@dataclass
class Snapshot:
    mark: int
    timestamp: str
    backups: dict = field(default_factory=dict)


class FileHistory:

    def __init__(self, directory, cwd, enabled: bool = True,
                 max_snapshots: int = MAX_SNAPSHOTS):
        self.directory = Path(directory)
        self.cwd = Path(cwd)
        self.enabled = bool(enabled)
        self.max_snapshots = int(max_snapshots)
        self.snapshots: list[Snapshot] = []
        self.tracked: list[str] = []
        if self.enabled:
            self._load()

    def _key(self, path) -> str:
        path = Path(path)
        try:
            return str(path.relative_to(self.cwd))
        except ValueError:
            return str(path)

    def _path(self, key: str) -> Path:
        return Path(key) if os.path.isabs(key) else self.cwd / key

    def _backup_name(self, key: str, version: int) -> str:
        absolute = os.path.realpath(self._path(key))
        digest = hashlib.sha256(absolute.encode()).hexdigest()[:16]
        return f'{digest}@v{version}'

    def _state_file(self) -> Path:
        return self.directory / STATE_FILE

    def _decode(self, stored: dict):
        self.tracked = [str(key) for key in stored.get('tracked', [])]
        self.snapshots = [
            Snapshot(mark=int(entry.get('mark', 0)),
                     timestamp=str(entry.get('timestamp', '')),
                     backups={
                         key: Backup(value.get('name'),
                                     int(value.get('version', 1)))
                         for key, value in entry.get('backups', {}).items()})
            for entry in stored.get('snapshots', [])]

    def _load(self):
        try:
            self._decode(json.loads(self._state_file().read_text(
                encoding='utf-8')))
        except (OSError, ValueError):
            return

    def _save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self._state_file().with_suffix('.tmp')
        temporary.write_text(json.dumps(self.dump(), indent=1) + '\n',
                             encoding='utf-8')
        os.replace(temporary, self._state_file())

    def _read(self, key: str) -> str | None:
        try:
            return self._path(key).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return None

    def _backup_text(self, backup: Backup) -> str | None:
        if backup.name is None:
            return None
        try:
            return (self.directory / backup.name).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return None

    def _unchanged(self, key: str, backup: Backup) -> bool:
        current = self._read(key)
        if current is None:
            return False
        return current == self._backup_text(backup)

    def _create_backup(self, key: str, version: int) -> Backup:
        source = self._path(key)
        if not source.exists():
            return Backup(None, version)
        self.directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self.directory / self._backup_name(key, version))
        return Backup(self._backup_name(key, version), version)

    def _latest(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def track_edit(self, path) -> None:
        if not self.enabled:
            return
        latest = self._latest()
        if latest is None:
            return
        key = self._key(path)
        if key in latest.backups:
            return
        latest.backups[key] = self._create_backup(key, 1)
        if key not in self.tracked:
            self.tracked.append(key)
        self._save()

    def snapshot(self, mark: int) -> None:
        if not self.enabled:
            return
        previous = self._latest()
        backups = {}
        for key in self.tracked:
            last = previous.backups.get(key) if previous else None
            version = last.version + 1 if last else 1
            if not self._path(key).exists():
                backups[key] = Backup(None, version)
            elif last and last.name is not None and self._unchanged(key, last):
                backups[key] = last
            else:
                backups[key] = self._create_backup(key, version)
        self.snapshots.append(Snapshot(int(mark), _now(), backups))
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots = self.snapshots[-self.max_snapshots:]
        self._save()

    def _snapshot(self, mark: int) -> Snapshot | None:
        for snap in reversed(self.snapshots):
            if snap.mark == int(mark):
                return snap
        return None

    def _target_backup(self, key: str,
                       target: Snapshot) -> Backup | None:
        backup = target.backups.get(key)
        if backup is not None:
            return backup
        for snap in self.snapshots:
            known = snap.backups.get(key)
            if known is not None:
                return known
        return None

    def can_restore(self, mark: int) -> bool:
        return self.enabled and self._snapshot(mark) is not None

    def rewind(self, mark: int) -> list[str]:
        if not self.enabled:
            return []
        target = self._snapshot(mark)
        if target is None:
            raise ValueError(f'No file history for turn {mark}')
        changed = []
        for key in self.tracked:
            backup = self._target_backup(key, target)
            if backup is None:
                continue
            path = self._path(key)
            if backup.name is None:
                try:
                    path.unlink()
                    changed.append(key)
                except OSError:
                    continue
                continue
            source = self.directory / backup.name
            if not source.exists() or self._unchanged(key, backup):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path)
            changed.append(key)
        return changed

    def diff_stats(self, mark: int) -> dict | None:
        if not self.enabled:
            return None
        target = self._snapshot(mark)
        if target is None:
            return None
        files = []
        insertions = 0
        deletions = 0
        for key in self.tracked:
            backup = self._target_backup(key, target)
            if backup is None:
                continue
            want = self._backup_text(backup)
            now = self._read(key)
            if want == now:
                continue
            files.append(key)
            matcher = difflib.SequenceMatcher(
                None, (now or '').splitlines(), (want or '').splitlines())
            for tag, _i1, i2, _j1, j2 in matcher.get_opcodes():
                if tag in ('insert', 'replace'):
                    insertions += j2 - _j1
                if tag in ('delete', 'replace'):
                    deletions += i2 - _i1
        return {'files': files, 'insertions': insertions,
                'deletions': deletions}

    def _first_backup(self, key: str) -> Backup | None:
        found = [snapshot.backups[key] for snapshot in self.snapshots
                 if key in snapshot.backups]
        return min(found, key=lambda backup: backup.version) if found else None

    def session_stats(self) -> dict:
        out: dict[str, dict] = {}
        if not self.enabled:
            return out
        for key in self.tracked:
            oldest = self._first_backup(key)
            now = self._read(key) or ''
            if oldest is None or oldest.name is None:
                lines = len(now.splitlines())
                if lines:
                    out[key] = {'insertions': lines, 'deletions': 0,
                                'created': True}
                continue
            want = self._backup_text(oldest) or ''
            if want == now:
                continue
            matcher = difflib.SequenceMatcher(
                None, want.splitlines(), now.splitlines())
            adds = deletes = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag in ('insert', 'replace'):
                    adds += j2 - j1
                if tag in ('delete', 'replace'):
                    deletes += i2 - i1
            out[key] = {'insertions': adds, 'deletions': deletes}
        return out

    def dump(self) -> dict:
        return {'tracked': list(self.tracked),
                'snapshots': [{'mark': snap.mark, 'timestamp': snap.timestamp,
                               'backups': {
                                   key: {'name': backup.name,
                                         'version': backup.version}
                                   for key, backup in snap.backups.items()}}
                              for snap in self.snapshots]}

    def restore(self, stored: dict) -> None:
        if self.enabled:
            self._decode(stored)
