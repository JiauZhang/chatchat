from __future__ import annotations

import os
import re
import secrets
import subprocess
import time
from pathlib import Path


WORKTREE_DIR = '.pyclaw/worktrees'
NAME_MAX = 64
STALE_DAYS = 30
_SEGMENT = re.compile(r'[A-Za-z0-9._-]+\Z')

ADJECTIVES = ('calm', 'clever', 'cosmic', 'daring', 'eager', 'gentle',
              'golden', 'hidden', 'lively', 'mellow', 'nimble', 'quiet',
              'rapid', 'serene', 'tidy', 'vivid')
VERBS = ('building', 'charting', 'digging', 'folding', 'gathering',
         'mapping', 'mending', 'planting', 'shaping', 'tracing', 'tuning',
         'weaving')
NOUNS = ('anchor', 'beacon', 'cabinet', 'delta', 'engine', 'garden',
         'harbour', 'lantern', 'meadow', 'orbit', 'pivot', 'quarry', 'ridge',
         'signal', 'thicket', 'vessel')


def word_slug() -> str:
    return (f'{secrets.choice(ADJECTIVES)}-{secrets.choice(VERBS)}-'
            f'{secrets.choice(NOUNS)}')


def validate_name(name: str) -> None:
    """A name is joined into a path and a ref, so a bad one can put a
    worktree — and its removal — somewhere the session never meant to go."""
    if len(name) > NAME_MAX:
        raise ValueError(f'worktree name must be {NAME_MAX} characters or '
                         f'fewer, not {len(name)}')
    for segment in name.split('/'):
        if segment in ('.', '..'):
            raise ValueError(f'worktree name "{name}" must not contain "." '
                             'or ".."')
        if not _SEGMENT.match(segment):
            raise ValueError(
                f'worktree name "{name}" is not usable: each "/"-separated '
                'part needs letters, digits, dots, underscores or dashes')


def flatten(name: str) -> str:
    """A nested name stays one directory deep: a worktree inside another is
    deleted along with it, uncommitted work and all."""
    return name.replace('/', '+')


def branch_name(name: str) -> str:
    return f'worktree-{flatten(name)}'


def _git(cwd, *args) -> subprocess.CompletedProcess:
    command = ('git', *args)
    try:
        return subprocess.run(command, cwd=str(cwd), capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 1, '', str(exc))


def in_repository(cwd) -> bool:
    return _git(cwd, 'rev-parse', '--is-inside-work-tree').returncode == 0


def repository_root(cwd) -> Path | None:
    """Every worktree hangs off the main checkout, including one made from
    inside a worktree, so none of them is left behind uncleaned."""
    top = _git(cwd, 'rev-parse', '--show-toplevel')
    return Path(top.stdout.strip()) if top.returncode == 0 else None


def head(cwd) -> tuple[str, str]:
    branch = _git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD')
    commit = _git(cwd, 'rev-parse', 'HEAD')
    return (branch.stdout.strip() if branch.returncode == 0 else '',
            commit.stdout.strip() if commit.returncode == 0 else '')


def default_branch(cwd) -> str:
    shown = _git(cwd, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
    if shown.returncode == 0:
        return shown.stdout.strip().split('/', 1)[-1]
    for candidate in ('main', 'master'):
        if _git(cwd, 'rev-parse', '--verify', f'refs/heads/{candidate}'
                ).returncode == 0:
            return candidate
    return ''


def _base_ref(cwd) -> str:
    """The work starts from what the remote already has, so what comes back
    can be pushed onto it. Without a reachable remote it starts from here."""
    branch = default_branch(cwd)
    if not branch:
        return 'HEAD'
    remote = f'origin/{branch}'
    if _git(cwd, 'rev-parse', '--verify', f'refs/remotes/{remote}'
            ).returncode == 0:
        return remote
    done = subprocess.run(('git', 'fetch', 'origin', branch), cwd=str(cwd),
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL,
                          env={**os.environ, 'GIT_TERMINAL_PROMPT': '0',
                               'GIT_ASKPASS': ''})
    return remote if done.returncode == 0 else 'HEAD'


def changes(worktree_path, base_commit: str) -> dict | None:
    """What is in the worktree that is not in the branch it came from. None
    means git could not say, and whoever deletes work must read that as
    unsafe."""
    status = _git(worktree_path, 'status', '--porcelain')
    if status.returncode != 0:
        return None
    files = sum(1 for line in status.stdout.split('\n') if line.strip())
    if not base_commit:
        return None
    counted = _git(worktree_path, 'rev-list', '--count',
                   f'{base_commit}..HEAD')
    if counted.returncode != 0:
        return None
    return {'files': files,
            'commits': int(counted.stdout.strip() or 0)}


def _head_of(path) -> str:
    """The commit a worktree is on, read through its .git pointer so an
    existing one is recognised without starting git at all."""
    try:
        git_dir = Path(Path(path, '.git').read_text(encoding='utf-8')
                       .strip().split(' ', 1)[1])
        return (git_dir / 'HEAD').read_text(encoding='utf-8').strip()
    except (OSError, IndexError):
        return ''


def worktree_path(root, name) -> Path:
    return Path(root) / WORKTREE_DIR / flatten(name)


def is_generated(name: str) -> bool:
    """Whether the name was given by `name_for` rather than by a person. Only
    those are swept: a worktree someone named is theirs to keep."""
    parts = name.split('-')
    return (len(parts) == 3 and parts[0] in ADJECTIVES and parts[1] in VERBS
            and parts[2] in NOUNS)


def _untouched(path) -> bool:
    """Nothing changed since the worktree opened and nothing sits on a commit
    no remote has. Unknown is read as unsafe. Untracked files count as a
    change: a worktree left behind by a session may hold the only copy."""
    status = _git(path, 'status', '--porcelain')
    if status.returncode != 0 or status.stdout.strip():
        return False
    ahead = _git(path, 'rev-list', '--count', 'HEAD', '--not', '--remotes')
    return ahead.returncode == 0 and int(ahead.stdout.strip() or 0) == 0


def sweep_worktrees(root, keep=(), days: int = STALE_DAYS) -> list[Path]:
    """Remove the auto-named worktrees nobody came back to, so a repository
    does not fill up with the leftovers of abandoned sessions. A worktree with
    changes, with commits no remote has, or that git cannot be asked about,
    stays where it is."""
    parent = Path(root) / WORKTREE_DIR
    if not parent.is_dir():
        return []
    cutoff = time.time() - days * 86400
    kept = {Path(one).resolve() for one in keep}
    gone = []
    for entry in sorted(parent.iterdir()):
        if not entry.is_dir() or not is_generated(entry.name):
            continue
        if entry.resolve() in kept or entry.stat().st_mtime > cutoff:
            continue
        if not _untouched(entry):
            continue
        try:
            remove({'path': entry, 'branch': branch_name(entry.name),
                    'root': root, 'origin': root})
        except ValueError:
            continue
        gone.append(entry)
    return gone


_slugs: dict[str, str] = {}


def name_for(session_key: str, root) -> str:
    """One readable name per conversation, kept for as long as the process
    does, so leaving a worktree and asking for the work again goes back to the
    same directory instead of opening a second one."""
    if session_key in _slugs:
        return _slugs[session_key]
    name = word_slug()
    while worktree_path(root, name).exists():
        name = word_slug()
    _slugs[session_key] = name
    return name


def create(cwd, name: str) -> dict:
    validate_name(name)
    origin = Path(cwd)
    root = repository_root(origin) or origin
    path = worktree_path(root, name)
    branch = branch_name(name)
    origin_branch, origin_commit = head(origin)
    resumed = _head_of(path)
    if resumed:
        return {'name': name, 'path': path, 'branch': branch, 'origin': origin,
                'root': root, 'origin_branch': origin_branch,
                'origin_head': resumed, 'resumed': True}
    base = _base_ref(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = _git(root, 'worktree', 'add', '-B', branch, str(path), base)
    if done.returncode != 0:
        raise ValueError((done.stderr or done.stdout).strip())
    started_at = _git(path, 'rev-parse', 'HEAD').stdout.strip()
    return {'name': name, 'path': path, 'branch': branch, 'origin': origin,
            'root': root, 'origin_branch': origin_branch,
            'origin_head': started_at or origin_commit, 'resumed': False}


def create_by_hook(cwd, name: str, path) -> dict:
    origin = Path(cwd)
    origin_branch, origin_commit = head(origin)
    return {'name': name, 'path': Path(path), 'branch': '', 'origin': origin,
            'root': origin, 'origin_branch': origin_branch,
            'origin_head': origin_commit, 'hook_based': True}


def remove(record: dict):
    origin = Path(record.get('root') or record['origin'])
    path = Path(record['path'])
    done = _git(origin, 'worktree', 'remove', '--force', str(path))
    if done.returncode != 0:
        raise ValueError((done.stderr or done.stdout).strip())
    if record.get('branch'):
        _git(origin, 'branch', '-D', record['branch'])
    return path
