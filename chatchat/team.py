from __future__ import annotations
import threading
from dataclasses import dataclass
from queue import Queue, Empty
from typing import Any

from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.message import ID, Message
from chatchat.scheduler import emit_event


@dataclass
class TeamConfig:
    name: str
    leader: AgentConfig


def create_team(config: TeamConfig, scheduler) -> Team:
    """Unified factory function for creating a team."""
    team = Team(config, scheduler)
    scheduler.register(team)
    team.start()
    return team


class Team:
    def __init__(self, config: TeamConfig, scheduler):
        self.id = ID(uid=config.name, kind='team', name=config.name)
        self.scheduler = scheduler

        self._mailbox = Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._leader = create_agent(config.leader, scheduler)

    def _emit(self, topic: str, data: dict = None):
        d = dict(data or {})
        d['_source'] = self.name
        emit_event(topic, d)

    @property
    def name(self) -> str:
        return self.id.name

    @property
    def leader(self) -> Agent:
        return self._leader

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        self._leader.start()

    def stop(self, timeout: float = 2.0):
        self._leader.stop(timeout=timeout)
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
                if msg.type == 'signal' and msg.subtype == 'stop':
                    self._stop_event.set()
                    continue
                try:
                    result = self.handle_message(msg)
                    if result is not None:
                        self.scheduler.reply(msg, result)
                except Exception as e:
                    self._emit('agent:error', {'error': str(e)})
                    self.scheduler.reply(msg, f'error: {e}')
            except Empty:
                continue

    def handle_message(self, msg: Message) -> Any:
        if msg.type in ('text', 'request', 'signal'):
            return self._leader.handle_message(msg)
        return None