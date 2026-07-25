import queue
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    topic: str
    data: dict = field(default_factory=dict)
    source: str = ''


class EventBus:
    def __init__(self, source=''):
        self._source = source
        self._queue: queue.Queue = queue.Queue()
        self._notify = threading.Event()
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, value):
        self._source = value

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._dispatch, daemon=True)
        self._thread.start()

    def stop(self):
        self._queue.put(None)
        self._notify.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._running = False

    def emit(self, topic: str, data: dict = None, source: str = ''):
        event = Event(topic, data or {}, source or self._source)
        self._queue.put(event)
        self._notify.set()

    def flush(self):
        self._queue.join()

    def subscribe(self, topic: str, handler: Callable):
        self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable):
        self._handlers[topic].remove(handler)
        if not self._handlers[topic]:
            del self._handlers[topic]

    def _match(self, event_topic: str, pattern: str) -> bool:
        if pattern == '*':
            return True
        if pattern.endswith(':*'):
            prefix = pattern[:-1]
            return event_topic.startswith(prefix)
        return event_topic == pattern

    def _dispatch(self):
        while self._running:
            self._notify.wait()
            self._notify.clear()
            while self._running:
                try:
                    event = self._queue.get_nowait()
                except queue.Empty:
                    break
                if event is None:
                    self._running = False
                    self._queue.task_done()
                    return
                for pattern, handlers in list(self._handlers.items()):
                    if not self._match(event.topic, pattern):
                        continue
                    for handler in handlers:
                        try:
                            handler(event)
                        except Exception:
                            pass
                self._queue.task_done()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()