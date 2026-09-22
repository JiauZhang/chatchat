from __future__ import annotations

import json
import shutil
from pathlib import Path

from chatchat.core.tasks import safe_component


CONFIG = 'config.json'


class TeamStore:

    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, name: str) -> Path:
        return self.directory / safe_component(name)

    def config_path(self, name: str) -> Path:
        return self.path(name) / CONFIG

    def exists(self, name: str) -> bool:
        return self.config_path(name).is_file()

    def create(self, name: str, description: str = '',
               leader: str = '') -> dict:
        if self.exists(name):
            raise ValueError(f'team {name} already exists')
        record = {'name': name, 'description': description, 'leader': leader,
                  'members': {}}
        self.path(name).mkdir(parents=True, exist_ok=True)
        self._write(name, record)
        return record

    def read(self, name: str) -> dict | None:
        try:
            record = json.loads(self.config_path(name).read_text(
                encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    def _write(self, name: str, record: dict):
        self.config_path(name).write_text(json.dumps(record, indent=2,
                                                     ensure_ascii=False) + '\n',
                                          encoding='utf-8')

    def note_member(self, name: str, member: dict):
        record = self.read(name)
        if not record:
            return
        record.setdefault('members', {})[str(member['agent_id'])] = member
        self._write(name, record)

    def drop_member(self, name: str, agent_id: str):
        record = self.read(name)
        if not record:
            return
        record.setdefault('members', {}).pop(str(agent_id), None)
        self._write(name, record)

    def members(self, name: str) -> list:
        record = self.read(name)
        return list((record or {}).get('members', {}).values())

    def delete(self, name: str):
        shutil.rmtree(self.path(name), ignore_errors=True)

    def list(self, leader: str = '') -> list:
        rows = []
        if not self.directory.is_dir():
            return rows
        for directory in sorted(self.directory.iterdir()):
            record = self.read(directory.name)
            if not record:
                continue
            if leader and record.get('leader') != leader:
                continue
            rows.append(record)
        return rows
