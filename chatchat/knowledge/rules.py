from __future__ import annotations

import re
from pathlib import Path

FRONTMATTER = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?', re.S)
WILDCARDS = ('**', '', '**/*')


def split_items(text: str) -> list[str]:
    out, depth, current = [], 0, ''
    for char in text:
        if char == '{':
            depth += 1
        elif char == '}':
            depth = max(0, depth - 1)
        if char == ',' and depth == 0:
            out.append(current)
            current = ''
        elif char == ' ' and depth == 0:
            if current.strip():
                out.append(current)
            current = ''
        else:
            current += char
    out.append(current)
    return [item.strip().strip('"\'') for item in out if item.strip()]


def expand_braces(pattern: str) -> list[str]:
    open_ = pattern.find('{')
    close = pattern.find('}', open_)
    if open_ < 0 or close < 0:
        return [pattern]
    head = pattern[:open_]
    tail = pattern[close + 1:]
    out = []
    for option in split_items(pattern[open_ + 1:close]):
        out.extend(expand_braces(f'{head}{option}{tail}'))
    return out


def _translate(pattern: str) -> str:
    body = pattern.lstrip('/')
    if body.endswith('/**'):
        body = body[:-3]
    out = ''
    index = 0
    while index < len(body):
        if body.startswith('/**/', index):
            out += '/(?:[^/]+/)*'
            index += 4
            continue
        if body.startswith('**/', index):
            out += '(?:[^/]+/)*'
            index += 3
            continue
        if body.startswith('/**', index):
            out += '/.*'
            index += 3
            continue
        char = body[index]
        if char == '*':
            out += '[^/]*'
        elif char == '?':
            out += '[^/]'
        elif char == '[':
            close = body.find(']', index)
            out += body[index:close + 1] if close > index else re.escape(char)
            index = close if close > index else index
        else:
            out += re.escape(char)
        index += 1
    return out


def matches(pattern: str, relative_path: str) -> bool:
    body = pattern.strip().strip('"\'')
    if body.endswith('/'):
        body = body[:-1]
    if body.endswith('/**'):
        body = body[:-3]
    if not body:
        return False
    anchored = '/' in body.lstrip('/')
    head = '' if anchored else '(?:.*/)?'
    regex = f'{head}{_translate(body)}(?:/.*)?$'
    return re.match(regex, relative_path.strip('/')) is not None


def parse(text: str) -> tuple[list[str], str]:
    """Return the globs a rule claims and its body without the frontmatter."""
    found = FRONTMATTER.match(text)
    if not found:
        return [], text.strip()
    globs: list[str] = []
    block = False
    for line in found.group(1).splitlines():
        if line.strip().startswith('paths:'):
            value = line.split(':', 1)[1].strip()
            if value:
                globs = split_items(value)
            else:
                block = True
            continue
        if block:
            item = line.strip()
            if not item.startswith('-'):
                break
            globs.extend(split_items(item[1:].strip()))
    return [expanded for glob in globs
            for expanded in expand_braces(glob)], text[found.end():].strip()


class Rule:

    def __init__(self, path: Path, scope: str, globs: list[str],
                 content: str, root: Path):
        self.path = path
        self.scope = scope
        self.globs = globs
        self.content = content
        self.root = root

    def covers(self, relative_path: str) -> bool:
        return any(matches(glob, relative_path) for glob in self.globs)


class RuleSet:
    """Markdown rules in a `rules` directory. The ones that name paths stay
    silent until the model touches a file they cover."""

    def __init__(self, roots: list[tuple[Path, Path, str]]):
        self.roots = [(Path(directory).resolve(), Path(anchor).resolve(), scope)
                      for directory, anchor, scope in roots]
        self.delivered: set[str] = set()
        self._found: list[Rule] | None = None

    @classmethod
    def discover(cls, cwd, home=None, subdir=None) -> 'RuleSet':
        workspace = Path(cwd)
        roots = []
        if subdir:
            roots.append((workspace / subdir / 'rules', workspace, 'project'))
        if home:
            roots.append((Path(home) / 'rules', workspace, 'user'))
        return cls(roots)

    def entries(self) -> list[Rule]:
        if self._found is None:
            found = []
            for directory, _, scope in self.roots:
                if not directory.is_dir():
                    continue
                for path in sorted(directory.rglob('*.md')):
                    globs, content = self._read(path)
                    found.append(Rule(path, scope, globs, content, directory))
            self._found = found
        return self._found

    @staticmethod
    def _read(path: Path) -> tuple[list[str], str]:
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            return [], ''
        return parse(text)

    def always(self) -> list[Rule]:
        return [rule for rule in self.entries() if not self._claims_paths(rule)]

    def all(self) -> list[Rule]:
        return [rule for rule in self.entries() if self._claims_paths(rule)]

    @staticmethod
    def _claims_paths(rule: Rule) -> bool:
        return bool(rule.globs) and not all(glob in WILDCARDS
                                            for glob in rule.globs)

    def relevant(self, file_path: str) -> list[Rule]:
        """Rules covering a file, given as an absolute path or as a path
        relative to the directory the rules are anchored at."""
        given = Path(str(file_path)).expanduser()
        found = []
        for directory, anchor, _ in self.roots:
            if given.is_absolute():
                target = given.resolve()
                if target == anchor or not target.is_relative_to(anchor):
                    continue
                rel = str(target.relative_to(anchor))
            else:
                rel = str(given)
            if rel.startswith('..'):
                continue
            for rule in self.entries():
                if rule.root != directory or str(rule.path) in self.delivered:
                    continue
                if self._claims_paths(rule) and rule.covers(rel):
                    found.append(rule)
        for rule in found:
            self.delivered.add(str(rule.path))
        return found

    def reset(self) -> None:
        self.delivered.clear()


def note(rules: list[Rule], file_path: str) -> str:
    if not rules:
        return ''
    blocks = [f'A rule for {file_path}, read from {rule.path}:\n\n{rule.content}'
              for rule in rules if rule.content]
    return '\n\n'.join(blocks)
