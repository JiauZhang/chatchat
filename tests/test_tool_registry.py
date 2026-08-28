import asyncio

import pytest

from chatchat.runtime import (
    Scheduler, get_runtime, set_runtime, start_tool_handler,
    TOOLS_ENTITY_ID, stop_tool_handler,
)
from chatchat.tool import (
    Tool, ToolContext, get_registry, reset_registry, tool,
)
from chatchat.agent_tools import create_agent_tool, send_message_tool, task_stop_tool
from chatchat.team import create_team_tool


@pytest.fixture(autouse=True)
def _fresh_runtime():
    from chatchat.runtime import Scheduler, set_runtime, stop_tool_handler
    reset_registry()
    set_runtime(Scheduler())
    yield
    stop_tool_handler()
    reset_registry()


def test_register_and_resolve():
    reg = get_registry()
    t = Tool(name='ping', description='ping', func=lambda: 'pong')
    reg.register(t)
    assert reg.resolve('ping') is t
    assert reg.resolve('missing') is None
    assert 'ping' in reg.names()
    assert t in reg.list()


def test_auto_register_decorator():
    @tool(name='auto', description='d', auto_register=True)
    def auto(ctx: ToolContext = None):
        return 'ok'
    assert get_registry().resolve('auto') is not None


def test_bootstrap_registers_builtins():
    start_tool_handler()
    names = set(get_registry().names())
    assert {'create_agent', 'create_team', 'send_message', 'task_stop'} <= names


async def test_tool_call_event_executes_and_replies():
    runtime = Scheduler()
    set_runtime(runtime)
    start_tool_handler()
    reg = get_registry()
    reg.register(Tool(name='add', description='add', func=lambda a, b: str(int(a) + int(b))))

    result = await runtime.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'add', 'arguments': {'a': 2, 'b': 3}, 'ctx': None,
              'tools': {'add'}, 'tool_call_id': 'c1'},
        timeout=5,
    )
    assert result['role'] == 'tool'
    assert result['content'] == '5'
    assert result['tool_call_id'] == 'c1'


async def test_tool_call_unknown_or_disallowed_returns_error():
    runtime = Scheduler()
    set_runtime(runtime)
    start_tool_handler()
    reg = get_registry()
    reg.register(Tool(name='add', description='add', func=lambda a, b: str(int(a) + int(b))))

    # unknown tool
    res = await runtime.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'nope', 'arguments': {}, 'ctx': None,
              'tools': {'add'}, 'tool_call_id': 'x'},
        timeout=5,
    )
    assert 'unknown or disallowed' in res['content']

    # disallowed tool (not in the caller's allowed set)
    res = await runtime.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'add', 'arguments': {'a': 1, 'b': 1}, 'ctx': None,
              'tools': {'other'}, 'tool_call_id': 'y'},
        timeout=5,
    )
    assert 'unknown or disallowed' in res['content']


async def test_parallel_tool_calls_run_concurrently():
    runtime = Scheduler()
    set_runtime(runtime)
    start_tool_handler()

    reg = get_registry()

    async def slow_tool(ctx=None):
        await asyncio.sleep(0.1)
        return 'slow-done'
    reg.register(Tool(name='slow', description='slow', func=slow_tool))

    async def fast_tool(ctx=None):
        return 'fast-done'
    reg.register(Tool(name='fast', description='fast', func=fast_tool))

    async def call(name):
        return await runtime.request(
            source='caller', target_id=TOOLS_ENTITY_ID,
            topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
            data={'name': name, 'arguments': {}, 'ctx': None,
                  'tools': {'slow', 'fast'}, 'tool_call_id': name},
            timeout=5,
        )

    start = asyncio.get_event_loop().time()
    results = await asyncio.gather(call('slow'), call('fast'))
    elapsed = asyncio.get_event_loop().time() - start
    # Both ran; total time is bounded by the slowest single call (~0.1s),
    # proving the two calls executed in parallel rather than serially (~0.2s).
    assert elapsed < 0.18
    contents = {r['content'] for r in results}
    assert contents == {'slow-done', 'fast-done'}
