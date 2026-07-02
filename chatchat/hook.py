from chatchat.types import Progress, ProgressType


class _HookEmitter:
    def __init__(self):
        self._start_handlers: list = []
        self._step_handlers: list = []
        self._end_handlers: list = []
        self._error_handlers: list = []
        self._interact_handlers: list = []

    def on_start(self, handler):
        self._start_handlers.append(handler)
        return self

    def on_step(self, handler):
        self._step_handlers.append(handler)
        return self

    def on_end(self, handler):
        self._end_handlers.append(handler)
        return self

    def on_error(self, handler):
        self._error_handlers.append(handler)
        return self

    def on_interact(self, handler):
        self._interact_handlers.append(handler)
        return self

    def _ask(self, question='', metadata=None):
        if not self._interact_handlers:
            return None
        for h in self._interact_handlers:
            reply = h(question, metadata or {})
            if reply is not None:
                return reply
        return None

    def _emit(self, type: ProgressType, content='', name='', step=0):
        progress = Progress(type=type, content=content, name=name, step=step)
        suffix = type.name.rsplit('_', 1)[-1]
        if suffix == 'START':
            for h in self._start_handlers:
                h(progress)
        elif suffix == 'STEP':
            for h in self._step_handlers:
                h(progress)
        elif suffix == 'END':
            for h in self._end_handlers:
                h(progress)
        elif suffix == 'ERROR':
            for h in self._error_handlers:
                h(progress)