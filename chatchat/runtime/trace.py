from __future__ import annotations

import json
import time

from chatchat.hooks.events import (AGENT_TEXT, AGENT_WARN, RuntimeEvent,
                                   register_runtime_handler)

_WRITE_KINDS = {'agent.reason_start', 'agent.tool_call', 'agent.turn_finished',
                'team.settled', 'agent.state', 'agent.job'}


class JsonlTrace:
    def __init__(self, path: str, *, echo_content: bool = False):
        self.path = path
        self._echo = echo_content
        self._fh = open(path, 'a', encoding='utf-8')
        self._unreg = register_runtime_handler(self._on_event)

    def _on_event(self, ev: RuntimeEvent):
        if not isinstance(ev, RuntimeEvent):
            return
        if ev.kind == AGENT_TEXT:
            if not self._echo:
                return
            payload = {'kind': ev.kind, 'agent': ev.agent, 'ts': time.time(),
                       'delta': ev.data.get('delta', '')}
        elif ev.kind == AGENT_WARN:
            payload = {'kind': ev.kind, 'agent': ev.agent, 'ts': time.time(),
                       'text': ev.data.get('text', '')}
        else:
            if ev.kind not in _WRITE_KINDS and ev.kind != AGENT_TEXT:
                return
            payload = {'kind': ev.kind, 'agent': ev.agent, 'ts': time.time(),
                       **ev.data}
        self._fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self._fh.flush()

    def close(self):
        self._unreg()
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def trace(path: str, *, echo_content: bool = False) -> JsonlTrace:
    return JsonlTrace(path, echo_content=echo_content)
