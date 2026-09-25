from __future__ import annotations

import subprocess
import uuid
from pathlib import Path


WORKTREE_DIR = '.pyclaw/worktrees'


def _git(cwd, *args) -> subprocess.CompletedProcess:
    command = ('git', *args)
    try:
        return subprocess.run(command, cwd=str(cwd), capture_output=True,
                              text=True)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 1, '', str(exc))


def in_repository(cwd) -> bool:
    return _git(cwd, 'rev-parse', '--is-inside-work-tree').returncode == 0


def generated_name() -> str:
    return f'work-{uuid.uuid4().hex[:6]}'


def create(cwd, name: str) -> dict:
    origin = Path(cwd)
    path = origin / WORKTREE_DIR / name
    branch = f'wt/{name}'
    path.parent.mkdir(parents=True, exist_ok=True)
    done = _git(origin, 'worktree', 'add', '-b', branch, str(path), 'HEAD')
    if done.returncode != 0:
        raise ValueError((done.stderr or done.stdout).strip())
    return {'name': name, 'path': path, 'branch': branch, 'origin': origin}


def remove(record: dict):
    origin, path = record['origin'], Path(record['path'])
    done = _git(origin, 'worktree', 'remove', '--force', str(path))
    if done.returncode != 0:
        raise ValueError((done.stderr or done.stdout).strip())
    _git(origin, 'branch', '-D', record['branch'])
    return path
