from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


ENTRYPOINT = 'MEMORY.md'

SNAPSHOT_META = 'snapshot.json'

SYNCED_META = '.snapshot-synced.json'

MAX_ENTRYPOINT_LINES = 200

MAX_ENTRYPOINT_CHARS = 25_000

SCOPES = ('user', 'project', 'local')

SCOPE_NOTES = {
    'user': 'These notes follow you into every project, so keep them general.',
    'project': 'These notes belong to this project and are shared with it, '
               'so keep them about this project.',
    'local': 'These notes stay on this machine and are not shared, so keep '
             'them about this project and this machine.'}


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


class AgentMemory:

    def __init__(self, roots: dict, snapshots: Path | None = None):
        self._roots = {scope: Path(path) for scope, path in roots.items()}
        self._snapshots = Path(snapshots) if snapshots is not None else None

    def directory(self, agent_type: str, scope: str) -> Path:
        return self._roots[scope] / agent_type.replace(':', '-')

    def contains(self, path: Path) -> bool:
        path = Path(path).resolve()
        for root in self._roots.values():
            if path == root.resolve() or root.resolve() in path.parents:
                return True
        return False

    def _entry(self, agent_type: str, scope: str) -> Path:
        return self.directory(agent_type, scope) / ENTRYPOINT

    def prompt(self, agent_type: str, scope: str) -> str:
        directory = self.directory(agent_type, scope)
        directory.mkdir(parents=True, exist_ok=True)
        lines = ['## Persistent agent notes',
                 f'You keep your own notes in {directory}. Read them before '
                 f'you start, and when you learn something worth keeping for '
                 f'the next time you run, add it there.',
                 SCOPE_NOTES[scope], '', f'### {ENTRYPOINT}']
        held = self._read(directory)
        if held:
            lines.append(held)
        else:
            lines.append('Your notes are empty so far. Anything you save '
                         'here will show up next time.')
        return '\n'.join(lines)

    def _read(self, directory: Path) -> str:
        try:
            raw = (directory / ENTRYPOINT).read_text(encoding='utf-8').strip()
        except OSError:
            return ''
        kept = raw.split('\n')[:MAX_ENTRYPOINT_LINES]
        text = '\n'.join(kept)[:MAX_ENTRYPOINT_CHARS]
        return text

    def _snapshot_dir(self, agent_type: str) -> Path | None:
        if self._snapshots is None:
            return None
        return self._snapshots / agent_type.replace(':', '-')

    def _published(self, directory: Path) -> str | None:
        try:
            meta = json.loads((directory / SNAPSHOT_META)
                              .read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        stamp = str(meta.get('updatedAt') or '')
        return stamp or None

    def _synced(self, directory: Path) -> str | None:
        try:
            meta = json.loads((directory / SYNCED_META)
                              .read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return str(meta.get('syncedFrom') or '') or None

    def _copy(self, source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            if not entry.is_file() or entry.name == SNAPSHOT_META:
                continue
            shutil.copyfile(entry, target / entry.name)

    def _note_synced(self, target: Path, stamp: str) -> None:
        (target / SYNCED_META).write_text(
            json.dumps({'syncedFrom': stamp}), encoding='utf-8')

    def _has_notes(self, directory: Path) -> bool:
        try:
            return any(entry.name.endswith('.md') and entry.is_file()
                       for entry in directory.iterdir())
        except OSError:
            return False

    def sync_snapshot(self, agent_type: str, scope: str) -> str:
        published = self._snapshot_dir(agent_type)
        if published is None:
            return 'none'
        stamp = self._published(published)
        if stamp is None:
            return 'none'
        local = self.directory(agent_type, scope)
        if not self._has_notes(local):
            self._copy(published, local)
            self._note_synced(local, stamp)
            return 'initialized'
        synced = _stamp(self._synced(local) or '')
        published_stamp = _stamp(stamp)
        if synced is None or published_stamp is None:
            return 'update'
        if published_stamp > synced:
            return 'update'
        return 'none'

    def apply_snapshot(self, agent_type: str, scope: str) -> str:
        published = self._snapshot_dir(agent_type)
        if published is None:
            return 'none'
        stamp = self._published(published)
        if stamp is None:
            return 'none'
        local = self.directory(agent_type, scope)
        local.mkdir(parents=True, exist_ok=True)
        for entry in local.iterdir():
            if entry.is_file() and entry.name.endswith('.md'):
                entry.unlink()
        self._copy(published, local)
        self._note_synced(local, stamp)
        return 'applied'
