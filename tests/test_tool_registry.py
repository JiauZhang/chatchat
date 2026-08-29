import asyncio

import pytest

from chatchat.core.runtime import Runtime
from chatchat.core.tool_handler import TOOLS_ENTITY_ID
from chatchat.tools.base import Tool, tool


def _runtime():
    rt = Runtime()
    rt.start()
    return rt


def test_register_and_resolve():
    rt = Runtime()
    t = Tool(name='ping', description='ping', func=lambda: 'pong')
    rt.registry.register(t)
    assert rt.registry.resolve('ping') is t
    assert rt.registry.resolve('missing') is None
    assert 'ping' in rt.registry.names()
    assert t in rt.registry.list()


def test_tool_decorator_constructs_independent():
    # @tool only builds a Tool, it does not self-register
    @tool(name='auto', description='d')
    def auto(ctx=None):
        return 'ok'
    assert isinstance(auto, Tool)
    rt = Runtime()
    assert rt.registry.resolve('auto') is None
    rt.registry.register(auto)
    assert rt.registry.resolve('auto') is auto


def test_bootstrap_registers_builtins():
    rt = Runtime()
    names = set(rt.registry.names())
    assert {'create_agent', 'create_team', 'send_message', 'task_stop'} <= names


async def test_tool_call_event_executes_and_replies():
    rt = _runtime()
    rt.registry.register(Tool(name='add', description='add', func=lambda a, b: str(int(a) + int(b))))

    result = await rt.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'add', 'arguments': {'a': 2, 'b': 3}, 'ctx': None,
              'tools': {'add'}, 'tool_call_id': 'c1'},
        timeout=5,
    )
    assert result['role'] == 'tool'
    assert result['content'] == '5'
    assert result['tool_call_id'] == 'c1'
    await rt.shutdown()


async def test_tool_call_unknown_or_disallowed_returns_error():
    rt = _runtime()
    rt.registry.register(Tool(name='add', description='add', func=lambda a, b: str(int(a) + int(b))))

    res = await rt.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'nope', 'arguments': {}, 'ctx': None,
              'tools': {'add'}, 'tool_call_id': 'x'},
        timeout=5,
    )
    assert 'unknown or disallowed' in res['content']

    res = await rt.request(
        source='caller', target_id=TOOLS_ENTITY_ID,
        topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
        data={'name': 'add', 'arguments': {'a': 1, 'b': 1}, 'ctx': None,
              'tools': {'other'}, 'tool_call_id': 'y'},
        timeout=5,
    )
    assert 'unknown or disallowed' in res['content']
    await rt.shutdown()


async def test_parallel_tool_calls_run_concurrently():
    rt = _runtime()

    async def slow_tool(ctx=None):
        await asyncio.sleep(0.1)
        return 'slow-done'
    rt.registry.register(Tool(name='slow', description='slow', func=slow_tool))

    async def fast_tool(ctx=None):
        return 'fast-done'
    rt.registry.register(Tool(name='fast', description='fast', func=fast_tool))

    async def call(name):
        return await rt.request(
            source='caller', target_id=TOOLS_ENTITY_ID,
            topic=f'entity:{TOOLS_ENTITY_ID}:request:tool:call',
            data={'name': name, 'arguments': {}, 'ctx': None,
                  'tools': {'slow', 'fast'}, 'tool_call_id': name},
            timeout=5,
        )

    start = asyncio.get_running_loop().time()
    results = await asyncio.gather(call('slow'), call('fast'))
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 0.18
    contents = {r['content'] for r in results}
    assert contents == {'slow-done', 'fast-done'}
    await rt.shutdown()