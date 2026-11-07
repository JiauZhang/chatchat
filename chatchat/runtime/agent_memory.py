from __future__ import annotations

from pathlib import Path

from chatchat.runtime.enums import MemoryScope

ENTRYPOINT = "MEMORY.md"

MAX_ENTRYPOINT_LINES = 200

MAX_ENTRYPOINT_CHARS = 25_000

SCOPES = MemoryScope.values()

SCOPE_NOTES = {
    MemoryScope.USER: "These notes follow you into every project, so keep them general.",
    MemoryScope.PROJECT: "These notes belong to this project and are shared with it, so keep them about this project.",
    MemoryScope.LOCAL: "These notes stay on this machine and are not shared, so keep them about this project and this machine.",
}


class AgentMemory:
    def __init__(self, roots: dict):
        self._roots = {scope: Path(path) for scope, path in roots.items()}

    def directory(self, agent_type: str, scope: MemoryScope | str) -> Path:
        scope = MemoryScope(scope)
        return self._roots[scope.value] / agent_type.replace(":", "-")

    def contains(self, path: Path) -> bool:
        path = Path(path).resolve()
        for root in self._roots.values():
            if path == root.resolve() or root.resolve() in path.parents:
                return True
        return False

    def prompt(self, agent_type: str, scope: MemoryScope | str) -> str:
        scope = MemoryScope(scope)
        directory = self.directory(agent_type, scope)
        directory.mkdir(parents=True, exist_ok=True)
        lines = [
            "## Persistent agent notes",
            f"You keep your own notes in {directory}. Read them before "
            f"you start, and when you learn something worth keeping for "
            f"the next time you run, add it there.",
            SCOPE_NOTES[scope],
            "",
            f"### {ENTRYPOINT}",
        ]
        held = self._read(directory)
        if held:
            lines.append(held)
        else:
            lines.append("Your notes are empty so far. Anything you save here will show up next time.")
        return "\n".join(lines)

    def _read(self, directory: Path) -> str:
        try:
            raw = (directory / ENTRYPOINT).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        kept = raw.split("\n")[:MAX_ENTRYPOINT_LINES]
        return "\n".join(kept)[:MAX_ENTRYPOINT_CHARS]
