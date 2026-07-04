from chatchat.hook import _HookEmitter
from chatchat.types import ProgressType, Progress


def test_emitter_creation():
    e = _HookEmitter()
    assert e._start_handlers == []
    assert e._step_handlers == []
    assert e._end_handlers == []
    assert e._error_handlers == []
    assert e._interact_handlers == []


def test_on_start():
    e = _HookEmitter()
    called = []

    def handler(p: Progress):
        called.append(p)

    e.on_start(handler)
    e._emit(ProgressType.AGENT_START, content='hello')
    assert len(called) == 1
    assert called[0].type == ProgressType.AGENT_START
    assert called[0].content == 'hello'


def test_on_step():
    e = _HookEmitter()
    called = []

    def handler(p: Progress):
        called.append(p)

    e.on_step(handler)
    e._emit(ProgressType.CLIENT_STEP, step=3)
    assert len(called) == 1
    assert called[0].type == ProgressType.CLIENT_STEP
    assert called[0].step == 3


def test_on_end():
    e = _HookEmitter()
    called = []

    def handler(p: Progress):
        called.append(p)

    e.on_end(handler)
    e._emit(ProgressType.TOOL_END, name='search')
    assert len(called) == 1
    assert called[0].type == ProgressType.TOOL_END
    assert called[0].name == 'search'


def test_on_error():
    e = _HookEmitter()
    called = []

    def handler(p: Progress):
        called.append(p)

    e.on_error(handler)
    e._emit(ProgressType.AGENT_ERROR, content='fail')
    assert len(called) == 1
    assert called[0].type == ProgressType.AGENT_ERROR
    assert called[0].content == 'fail'


def test_multiple_handlers():
    e = _HookEmitter()
    results = []

    def h1(p):
        results.append('h1')

    def h2(p):
        results.append('h2')

    e.on_start(h1).on_start(h2)
    e._emit(ProgressType.AGENT_START)
    assert results == ['h1', 'h2']


def test_routing_correct_handler():
    """Each event type only triggers its own handler category."""
    e = _HookEmitter()
    start_calls = []
    step_calls = []
    end_calls = []
    error_calls = []

    e.on_start(lambda p: start_calls.append(p))
    e.on_step(lambda p: step_calls.append(p))
    e.on_end(lambda p: end_calls.append(p))
    e.on_error(lambda p: error_calls.append(p))

    e._emit(ProgressType.TOOL_START)
    assert len(start_calls) == 1
    assert len(step_calls) == 0
    assert len(end_calls) == 0
    assert len(error_calls) == 0

    e._emit(ProgressType.CLIENT_STEP)
    assert len(start_calls) == 1
    assert len(step_calls) == 1
    assert len(end_calls) == 0
    assert len(error_calls) == 0

    e._emit(ProgressType.AGENT_END)
    assert len(start_calls) == 1
    assert len(step_calls) == 1
    assert len(end_calls) == 1
    assert len(error_calls) == 0

    e._emit(ProgressType.TOOL_ERROR)
    assert len(start_calls) == 1
    assert len(step_calls) == 1
    assert len(end_calls) == 1
    assert len(error_calls) == 1


def test_interact():
    e = _HookEmitter()

    def interact_handler(question, metadata):
        return f'answered: {question}'

    e.on_interact(interact_handler)
    result = e._ask('continue?', {'key': 'val'})
    assert result == 'answered: continue?'


def test_interact_no_handler():
    e = _HookEmitter()
    result = e._ask('question')
    assert result is None


def test_interact_first_non_none():
    results = []

    def h1(q, m):
        results.append('h1')
        return None

    def h2(q, m):
        results.append('h2')
        return 'reply'

    e = _HookEmitter()
    e.on_interact(h1).on_interact(h2)
    result = e._ask('test')
    assert result == 'reply'
    assert results == ['h1', 'h2']


def test_progress_data_field():
    e = _HookEmitter()
    called = []

    def handler(p: Progress):
        called.append(p.data)

    e.on_start(handler)
    e._emit(ProgressType.TOOL_START, data={'arguments': {'x': 1}})
    assert called[0] == {'arguments': {'x': 1}}


def test_progress_type_category():
    assert ProgressType.AGENT_START.category == 'start'
    assert ProgressType.AGENT_STEP.category == 'step'
    assert ProgressType.AGENT_END.category == 'end'
    assert ProgressType.AGENT_ERROR.category == 'error'
    assert ProgressType.CLIENT_START.category == 'start'
    assert ProgressType.TOOL_START.category == 'start'
    assert ProgressType.TOOL_ERROR.category == 'error'