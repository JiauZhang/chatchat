from __future__ import annotations

import shutil
from pathlib import Path

from chatchat.tasks.tasks import TaskList


class Courier:
    """The team's name, where its mailboxes live, and what happens when it
    changes or is thrown away.

    A team is a named thing that can be gathered under a shared name and then
    discarded: the mailbox directory follows the name, the task list belongs to
    it, and leaving it while a teammate is still working has to be refused.
    """

    def __init__(self, name: str, *, mailbox_root=None, tasks_root=None, team_store=None):
        self.name = name
        self.team_store = team_store
        self.team_context: dict | None = None
        self._mailbox_root = Path(mailbox_root) if mailbox_root else None
        self._tasks_root = Path(tasks_root) if tasks_root else None
        self.tasks = TaskList(self._tasks_root / name) if self._tasks_root else None
        self.mailbox_dir = self._directory_for(name)

    def _directory_for(self, name: str) -> Path | None:
        if self._mailbox_root is None:
            return None
        return self._mailbox_root / name / "inboxes"

    def mailbox_path(self, member: str) -> Path:
        return self.mailbox_dir / f"{member}.json"

    def join(self, name: str, description: str = "", *, leader_id: str, session_id: str):
        if self.team_context is not None:
            raise ValueError(f"already in the team {self.name}")
        name = str(name or "").strip()
        if not name:
            raise ValueError("a team needs a name")
        if self.team_store is not None:
            name = self.team_store.unique_name(name)
            self.team_store.create(name, description, leader=leader_id, session_id=session_id)
        self.name = name
        self.mailbox_dir = self._directory_for(name)
        self.tasks = TaskList(self._tasks_root / name) if self._tasks_root is not None else None
        self.team_context = {"name": name, "description": description}
        return self.team_context

    def leave(self, live_teammates: list) -> None:
        if self.team_context is None:
            return
        if live_teammates:
            raise ValueError("the team still has teammates: " + ", ".join(live_teammates))
        if self.team_store is not None:
            self.team_store.delete(self.name)
        if self.tasks is not None:
            shutil.rmtree(self.tasks.directory, ignore_errors=True)
        self.team_context = None
