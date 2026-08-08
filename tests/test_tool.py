from chatchat.tool import Tool, Tools, tool


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


def test_tool_error():
    def failing(a):
        raise ValueError('something broke')

    t = Tool(name='fail', description='a failing tool', tool=failing)
    result = t(a=1)
    assert 'Error calling tool' in result
    assert 'something broke' in result


def test_tool_no_parameters():
    t = Tool(name='ping', description='ping tool', tool=lambda: 'pong')
    result = t()
    assert result == 'pong'


def test_tools_basic():
    a = Tool(name='a', description='tool a', tool=lambda: 'a')
    b = Tool(name='b', description='tool b', tool=lambda: 'b')
    tools = Tools(a, b)

    assert tools['a'] is a
    assert tools['b'] is b
    assert 'a' in tools
    assert 'c' not in tools

    names = [t.name for t in tools]
    assert names == ['a', 'b']


def test_tools_to_dict():
    a = Tool(name='a', description='tool a', tool=lambda: 'a')
    tools = Tools(a)
    dicts = tools.to_dict()
    assert len(dicts) == 1
    assert dicts[0]['function']['name'] == 'a'