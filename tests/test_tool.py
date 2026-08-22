import asyncio
from types import SimpleNamespace

import pytest

from chatchat.tool import Tool, Tools, tool, ToolContext
from chatchat.agent_loop import AgentLoop
from chatchat.exceptions import MaxStepsError
from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message, ToolCall


async def test_tool_decorator():
    @tool(name='test_func', description='a test function')
    def test_func(x: int):
        return x * 2

    assert isinstance(test_func, Tool)
    assert test_func.name == 'test_func'
    assert test_func.description == 'a test function'
    assert await test_func(x=5) == 10


def test_tool_to_dict():
    t = Tool(
        name='echo', description='echo the input',
        func=lambda x: x,
        parameters={
            'type': 'object',
            'properties': {'x': {'type': 'string'}},
            'required': ['x'],
        },
    )
    d = t.to_dict()
    assert d['type'] == 'function'
    assert d['function']['name'] == 'echo'
    assert d['function']['description'] == 'echo the input'


async def test_tool_error():
    def failing(a):
        raise ValueError('something broke')

    t = Tool(name='fail', description='a failing tool', func=failing)
    result = await t(a=1)
    assert 'Error calling tool' in result
    assert 'something broke' in result


async def test_tool_no_parameters():
    t = Tool(name='ping', description='ping tool', func=lambda: 'pong')
    result = await t()
    assert result == 'pong'


def test_tools_basic():
    a = Tool(name='a', description='tool a', func=lambda: 'a')
    b = Tool(name='b', description='tool b', func=lambda: 'b')
    tools = Tools(a, b)

    assert tools['a'] is a
    assert tools['b'] is b
    assert 'a' in tools
    assert 'c' not in tools

    names = [t.name for t in tools]
    assert names == ['a', 'b']


def test_tools_to_dict():
    a = Tool(name='a', description='tool a', func=lambda: 'a')
    tools = Tools(a)
    dicts = tools.to_dict()
    assert len(dicts) == 1
    assert dicts[0]['function']['name'] == 'a'


def test_tool_definition():
    t = Tool(name='roll', description='roll', func=lambda: 'x')
    assert t.name == 'roll'
    assert t.to_dict()['function']['name'] == 'roll'


async def test_ctx_injection():
    seen = {}

    @tool(name='record', description='record the caller')
    def record(ctx=None):
        seen[ctx.agent.name] = True
        return ctx.agent.name

    assert await record(ctx=ToolContext(agent=SimpleNamespace(name='player1'))) == 'player1'
    assert await record(ctx=ToolContext(agent=SimpleNamespace(name='player2'))) == 'player2'
    assert set(seen) == {'player1', 'player2'}


async def test_shared_tool_reentrant_parallel():
    seen = {}

    @tool(name='roll_dice', description='roll')
    def roll_dice(ctx=None):
        seen[ctx.agent.name] = seen.get(ctx.agent.name, 0) + 1
        return str(seen[ctx.agent.name])

    results = await asyncio.gather(
        roll_dice(ctx=ToolContext(agent=SimpleNamespace(name='player1'))),
        roll_dice(ctx=ToolContext(agent=SimpleNamespace(name='player2'))),
        roll_dice(ctx=ToolContext(agent=SimpleNamespace(name='player3'))),
        roll_dice(ctx=ToolContext(agent=SimpleNamespace(name='player1'))),
    )
    assert set(seen) == {'player1', 'player2', 'player3'}
    assert results == ['1', '1', '1', '2']


class _MockClient:
    def __init__(self):
        self.count = 0
        self._latest = None

    async def chat(self, messages, *, thinking=False, tools=None, **kwargs):
        self.count += 1
        self._latest = Message()
        if self.count == 1:
            delta = Delta(tool_calls=[ToolCall(
                index=0, id='1', name='roll_dice', arguments='{}',
            )])
        else:
            delta = Delta(content='3')
        self._latest.accumulate(delta)
        yield ChatCompletionChunk(choices=[ChunkChoice(delta=delta)])

    @property
    def latest(self):
        return self._latest


async def test_loop_injects_ctx_into_shared_tool():
    seen = {}

    @tool(name='roll_dice', description='roll')
    def roll_dice(ctx=None):
        seen[ctx.agent.name] = True
        return str(6)

    tools = Tools(roll_dice)
    loop = AgentLoop(_MockClient(), tools, max_steps=2, thinking=False, name='player7')
    result = await loop.run('roll a six-sided die using roll_dice')
    assert seen == {'player7': True}
    assert result == '3'


async def test_loop_raises_when_exceeding_max_steps():
    @tool(name='roll_dice', description='roll')
    def roll_dice(ctx=None):
        return str(6)

    tools = Tools(roll_dice)
    loop = AgentLoop(_MockClient(), tools, max_steps=1, thinking=False, name='player7')
    with pytest.raises(MaxStepsError):
        await loop.run('roll a six-sided die using roll_dice')