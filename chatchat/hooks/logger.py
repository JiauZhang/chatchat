from chatchat.hooks.events import (AGENT_REASON_START, AGENT_TEXT,
                                   AGENT_TURN_FINISHED, AGENT_WARN, RuntimeEvent,
                                   register_hook_event_handler,
                                   register_runtime_handler)
from chatchat.hooks.schemas import get_hook_display_text


def default_hook_logger(event):
    prefix = f'[{event.hook_event:<10}  {event.hook_name:>12}]'
    if event.type == 'started':
        print(f'{prefix} started', flush=True)
    elif event.type == 'response':
        line = f'{prefix} {event.outcome}'
        if event.outcome not in ('success', '') and event.stderr:
            line += f' stderr={event.stderr[:80]}'
        print(line, flush=True)


def install_default_logger():
    register_hook_event_handler(default_hook_logger)


class _PerAgentRenderer:

    def __init__(self):
        self.text_hdr = False
        self.reasoning = False

    def reset(self):
        self.text_hdr = False
        self.reasoning = False


_render_states: dict[str, _PerAgentRenderer] = {}


def runtime_print_handler(ev: RuntimeEvent):
    if isinstance(ev, RuntimeEvent):
        _render_runtime(ev)
    else:
        default_hook_logger(ev)


def _render_runtime(ev: RuntimeEvent):
    name = ev.agent
    state = _render_states.get(name)
    if state is None:
        state = _render_states[name] = _PerAgentRenderer()
    if ev.kind == AGENT_WARN:
        text = ev.data.get('text', '')
        print(f'\n[{name}] {text}', flush=True)
        state.reset()
    elif ev.kind == AGENT_REASON_START:
        if not state.reasoning:
            print(f'\n[{name}] (思考中...', end='', flush=True)
            state.reasoning = True
    elif ev.kind == AGENT_TEXT:
        pass
    elif ev.kind == AGENT_TURN_FINISHED:
        if state.reasoning:
            print('', flush=True)
        state.reset()
        _render_states.pop(name, None)


def install_runtime_print():
    register_runtime_handler(runtime_print_handler)
