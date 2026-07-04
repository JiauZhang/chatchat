from chatchat.tool import Tool, Tools, tool
from chatchat.types import ProgressType, Progress


def test_tool_decorator():
    @tool(name='test_func', description='a test function')
    def test_func(x: int):
        return x * 2

    assert isinstance(test_func, Tool)
    assert test_func.name == 'test_func'
    assert test_func.description == 'a test function'
    assert test_func(x=5) == 10


def test_tool_to_dict():
    t = Tool(
        name='echo', description='echo the input',
        tool=lambda x: x,
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


def test_tool_emits_events():
    events = []

    def collector(p: Progress):
        events.append((p.type, p.name, p.data))

    t = Tool(name='add', description='add two numbers', tool=lambda a, b: a + b)
    t.on_start(collector).on_end(collector).on_error(collector)

    result = t(a=3, b=4)

    assert result == 7
    assert len(events) == 2
    assert events[0][0] == ProgressType.TOOL_START
    assert events[0][1] == 'add'
    assert events[0][2] == {'arguments': {'a': 3, 'b': 4}}
    assert events[1][0] == ProgressType.TOOL_END
    assert events[1][1] == 'add'
    assert 'result' in events[1][2]


def test_tool_error():
    events = []

    def collector(p: Progress):
        events.append((p.type, p.name, p.content, p.data))

    def failing(a):
        raise ValueError('something broke')

    t = Tool(name='fail', description='a failing tool', tool=failing)
    t.on_start(collector).on_end(collector).on_error(collector)

    result = t(a=1)

    assert 'Error calling tool' in result
    assert 'something broke' in result
    assert len(events) == 2
    assert events[0][0] == ProgressType.TOOL_START
    assert events[1][0] == ProgressType.TOOL_ERROR
    assert 'something broke' in events[1][3].get('error', '')


def test_tool_no_parameters():
    t = Tool(name='ping', description='ping tool', tool=lambda: 'pong')
    result = t()
    assert result == 'pong'


def test_tools_creation():
    a = Tool(name='a', description='tool a', tool=lambda: 'a')
    b = Tool(name='b', description='tool b', tool=lambda: 'b')
    tools = Tools(a, b)

    assert tools['a'] is a
    assert tools['b'] is b
    assert 'a' in tools
    assert 'c' not in tools


def test_tools_iteration():
    a = Tool(name='a', description='tool a', tool=lambda: 'a')
    b = Tool(name='b', description='tool b', tool=lambda: 'b')
    tools = Tools(a, b)

    names = [t.name for t in tools]
    assert names == ['a', 'b']


def test_tools_to_dict():
    a = Tool(name='a', description='tool a', tool=lambda: 'a')
    tools = Tools(a)
    dicts = tools.to_dict()
    assert len(dicts) == 1
    assert dicts[0]['function']['name'] == 'a'