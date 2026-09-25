from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


class SidechainWriter:
    def __init__(self, directory, name: str, team_name: str,
                 subagent_type: str, prompt: str):
        self.directory = Path(directory)
        self.name = name
        self.agent_id = f'{name}@{team_name}'
        self.jsonl_path = self.directory / f'agent-{name}.jsonl'
        self.meta_path = self.directory / f'agent-{name}.meta.json'
        self._parent_uuid = None
        self._started = time.time()
        self._subagent_type = subagent_type
        self._prompt = prompt
        self._write_meta('running')

    def append(self, message: dict):
        record = dict(message)
        record['uuid'] = uuid.uuid4().hex
        record['parentUuid'] = self._parent_uuid
        record['agentId'] = self.agent_id
        record['isSidechain'] = True
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        self._parent_uuid = record['uuid']

    def finish(self, status: str):
        self._write_meta(status)

    def _write_meta(self, status: str):
        self.directory.mkdir(parents=True, exist_ok=True)
        meta = {'agentId': self.agent_id,
                'subagentType': self._subagent_type,
                'prompt': self._prompt,
                'status': status,
                'startedAt': self._started,
                'finishedAt': time.time()}
        self.meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
