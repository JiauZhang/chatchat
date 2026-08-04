from __future__ import annotations
import threading
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any

from chatchat.message import ID, Message


class _EventProxy:
    def __init__(self, scheduler, worker_id):
        self._scheduler = scheduler
        self._worker_id = worker_id

    def emit(self, topic, data=None, source=''):
        self._scheduler.publish(topic, Message(
            sender=self._worker_id,
            recipient=ID(uid='__all__', kind='system'),
            type='event', subtype=topic, payload=data or {},
        ))

    def start(self):
        pass

    def stop(self):
        pass

    def subscribe(self, topic, handler):
        pass

    def unsubscribe(self, topic, handler):
        pass


@dataclass
class WorkerConfig:
    name: str
    provider: str | None = None
    model: str | None = None
    instruction: str = ''
    stream: bool = True
    thinking: bool = False
    tools: list | None = None
    skills: list | None = None
    http_options: dict | None = None


class Worker:
    def __init__(self, config: WorkerConfig, scheduler):
        self.id = ID(uid=config.name, kind='worker', name=config.name)
        self.scheduler = scheduler
        self._mailbox = Queue()
        self._stop_event = threading.Event()
        self._thread = None
        self._agent = None

        if config.provider and config.model:
            from chatchat.agent import Agent
            self._agent = Agent(
                event_bus=_EventProxy(scheduler, self.id),
                name=config.name,
                provider=config.provider,
                model=config.model,
                instruction=config.instruction,
                stream=config.stream,
                thinking=config.thinking,
                tools=config.tools,
                skills=config.skills,
                http_options=config.http_options,
            )

    def _add_tool(self, tool):
        if self._agent:
            tool._bus = self._agent._bus
            tool._source = self._agent.name
            if self._agent.tools is None:
                from chatchat.tool import Tools
                self._agent.tools = Tools(tool)
            else:
                self._agent.tools.name_to_tool[tool.name] = tool
                self._agent.tools.tools = self._agent.tools.tools + (tool,)

    @property
    def name(self) -> str:
        return self.id.name

    def handle_message(self, msg: Message) -> Any:
        if msg.type == 'text':
            if self._agent:
                return self._agent._handle_chat(msg.payload)
            return 'Error: no LLM capability configured'
        if msg.type == 'signal':
            return self._handle_signal(msg)
        if msg.type == 'request':
            return self._handle_request(msg)
        return None

    def _handle_signal(self, msg: Message) -> str:
        if msg.subtype == 'stop':
            self.stop()
            return 'stopped'
        return f'unknown signal: {msg.subtype}'

    def _handle_request(self, msg: Message) -> Any:
        if msg.subtype == 'ping':
            return 'pong'
        if msg.subtype == 'status':
            return {
                'name': self.id.name,
                'running': self._thread is not None and self._thread.is_alive(),
                'has_agent': self._agent is not None,
            }
        return None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
                if msg.type == 'signal' and msg.subtype == 'stop':
                    self._stop_event.set()
                    continue
                result = self.handle_message(msg)
                if result is not None:
                    self.scheduler.reply(msg, result)
            except Empty:
                continue

    def stop(self, timeout: float = 2.0):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()