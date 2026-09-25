from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path, PurePath

import yaml


MAX_LISTING_DESC_CHARS = 250
ELLIPSIS = '…'
ARGUMENTS = '$ARGUMENTS'
LISTING_CONTEXT_PERCENT = 0.01
CHARS_PER_TOKEN = 4
DEFAULT_LISTING_CHARS = 8_000


def listing_budget(context_window: int = 0) -> int:
    if context_window <= 0:
        return DEFAULT_LISTING_CHARS
    return max(1, int(context_window * CHARS_PER_TOKEN
                      * LISTING_CONTEXT_PERCENT))


def _split(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        raise ValueError('frontmatter block is missing')
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            return ''.join(lines[1:index]), ''.join(lines[index + 1:])
    raise ValueError('frontmatter block is not closed')


def _names(value) -> tuple:
    if isinstance(value, str):
        return tuple(word.strip() for word in value.split(',') if word.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(word).strip() for word in value if str(word).strip())
    return ()


@dataclass
class Skill:
    name: str
    description: str
    when_to_use: str = ''
    allowed_tools: tuple = ()
    paths: tuple = ()
    model: str = ''
    source: str = 'user'
    directory: Path = None
    body_text: str | None = None

    @property
    def body(self) -> str:
        if self.body_text is None:
            try:
                _front, body = _split(
                    (self.directory / 'SKILL.md').read_text(encoding='utf-8'))
            except OSError:
                body = ''
            self.body_text = body.lstrip('\n')
        return self.body_text

    def render(self, args: str = '') -> str:
        text = self.body
        if not args:
            return text
        if ARGUMENTS in text:
            return text.replace(ARGUMENTS, args)
        return text.rstrip('\n') + f'\n\nArgs: {args}\n'

    def matches(self, path: str) -> bool:
        if not self.paths:
            return True
        pure = PurePath(path)
        return any(fnmatch.fnmatch(path, pattern)
                   or fnmatch.fnmatch(pure.name, pattern)
                   for pattern in self.paths)


@dataclass
class SkillRegistry:
    skills: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    @classmethod
    def discover(cls, cwd, home, subdir: str = '.pyclaw') -> 'SkillRegistry':
        return cls.load([(Path(cwd) / subdir / 'skills', 'project'),
                         (Path(home) / 'skills', 'user')])

    @classmethod
    def load(cls, roots) -> 'SkillRegistry':
        registry = cls()
        for root, source in roots:
            registry._load(Path(root), source)
        return registry

    def _load(self, root: Path, source: str):
        if not root.is_dir():
            return
        for directory in sorted(root.iterdir()):
            file = directory / 'SKILL.md'
            if not file.is_file():
                continue
            skill, problem = _read(directory, file, source)
            if skill is None:
                self.problems.append(problem)
                continue
            self.skills.setdefault(skill.name, skill)

    def all(self) -> list:
        return sorted(self.skills.values(), key=lambda skill: skill.name)

    def get(self, name: str):
        return self.skills.get(name)

    def entries(self) -> list:
        rows = []
        for skill in self.all():
            description = skill.description
            if skill.when_to_use:
                description = f'{description} - {skill.when_to_use}'
            if len(description) > MAX_LISTING_DESC_CHARS:
                description = (description[:MAX_LISTING_DESC_CHARS - 1]
                               + ELLIPSIS)
            rows.append((skill.name, description))
        return rows

    def listing(self, budget: int) -> str:
        rows = self.entries()
        if not rows:
            return ''
        full = '\n'.join(f'- {name}: {description}'
                         for name, description in rows)
        if len(full) <= budget:
            return full
        fixed = sum(len(f'- {name}: ') for name, _row in rows)
        room = budget - fixed - (len(rows) - 1)
        per = max(1, room // len(rows))
        lines = []
        for name, description in rows:
            if len(description) > per:
                description = (description[:max(1, per - 1)] + ELLIPSIS
                               if per > 1 else ELLIPSIS)
            lines.append(f'- {name}: {description}')
        return '\n'.join(lines)


def _read(directory: Path, file: Path, source: str):
    try:
        front, _body = _split(file.read_text(encoding='utf-8'))
        meta = yaml.safe_load(front)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return None, f'{directory.name}: {exc}'
    if not isinstance(meta, dict):
        return None, f'{directory.name}: frontmatter is not a mapping'
    name = str(meta.get('name') or directory.name)
    description = str(meta.get('description') or '').strip()
    if not description:
        return None, f'{name}: no description to match a request against'
    model = str(meta.get('model') or '')
    return Skill(name=name, description=description,
                 when_to_use=str(meta.get('when_to_use') or '').strip(),
                 allowed_tools=_names(meta.get('allowed-tools')),
                 paths=_names(meta.get('paths')),
                 model='' if model == 'inherit' else model, source=source,
                 directory=directory), ''
