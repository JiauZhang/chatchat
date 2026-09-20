import asyncio
from pathlib import Path

from chatchat.core.team import Team
from chatchat.tool import (DEFAULT_MAX_RESULT_CHARS, Tool, ToolContext,
                           ToolResult)
from helpers import mock_team

CTX = ToolContext(cwd=Path('/tmp/work'))


def test_context_is_injected_as_first_positional():
    seen = {}

    def read(context, file_path: str) -> str:
        seen['cwd'] = context.cwd
        return f'{file_path} under {context.cwd.name}'

    t = Tool(tool=read, name='Read', description='reads')
    out = asyncio.run(t(CTX, file_path='a.py'))
    assert out == 'a.py under work'
    assert seen['cwd'] == Path('/tmp/work')


def test_description_may_be_resolved_from_context():
    def dynamic(context):
        return f'searches {context.cwd.name} only'

    static = Tool(tool=lambda context: 'ok', name='LS',
                  description='lists a directory')
    callable_ = Tool(tool=lambda context: 'ok', name='LS',
                     description=dynamic)
    assert static.describe(CTX) == 'lists a directory'
    assert callable_.describe(CTX) == 'searches work only'


def test_capabilities_fail_closed_when_a_tool_declares_none():
    t = Tool(tool=lambda context: 'ok', name='Fetch', description='f')
    assert t.read_only is False
    assert t.get_path is None


def test_read_only_is_a_capability_of_the_tool():
    def reader(context, file_path: str = ''):
        return ''

    t = Tool(tool=reader, name='Read', description='r', read_only=True,
             get_path=lambda args: args.get('file_path'))
    assert t.read_only is True
    assert t.get_path({'file_path': 'a.py'}) == 'a.py'
    assert t.get_path({}) is None


def test_a_result_over_the_budget_is_cut_with_a_note_saying_so():
    def long(context, filler: str = ''):
        return 'x' * 5000

    t = Tool(tool=long, name='Dump', description='d', max_result_chars=1000)
    out = asyncio.run(t(CTX))
    assert len(out) <= 1000
    assert 'truncated' in out
    assert Tool(tool=long, name='D', description='d').max_result_chars \
        == DEFAULT_MAX_RESULT_CHARS


def test_a_result_inside_the_budget_is_untouched():
    def short(context):
        return ToolResult(text='exactly this', meta={'num_lines': 1})

    t = Tool(tool=short, name='S', description='s', max_result_chars=1000)
    out = asyncio.run(t(CTX))
    assert out.text == 'exactly this'
    assert out.meta == {'num_lines': 1}


def test_tool_failure_reports_the_real_reason():
    def boom(context, path: str = ''):
        raise ValueError('no such directory')

    async def main():
        team = Team('t', client_factory=lambda inst, model=None: None,
                    tool_context=CTX,
                    tools=[Tool(tool=boom, name='Boom', description='b')])
        return await team.execute_tool('Boom', {}, team.lead, 't1')

    out = asyncio.run(main())
    assert 'no such directory' in out.text
    assert 'ValueError' in out.text


def test_on_end_sees_the_awaited_result_of_an_async_tool():
    seen = []

    async def slow(context, q: str = '') -> ToolResult:
        await asyncio.sleep(0)
        return ToolResult(text='2 hits', meta={'num_lines': 2})

    t = Tool(tool=slow, name='Grep', description='g',
             on_end=lambda tool_, result: seen.append(result))
    out = asyncio.run(t(CTX, q='x'))
    assert isinstance(out, ToolResult)
    assert seen == [out]


def test_on_error_receives_the_exception():
    seen = []

    def bad(context):
        raise RuntimeError('disk on fire')

    t = Tool(tool=bad, name='Bad', description='b',
             on_error=lambda tool_, exc: seen.append(exc))
    try:
        asyncio.run(t(CTX))
    except RuntimeError as e:
        assert str(e) == 'disk on fire'
    assert isinstance(seen[0], RuntimeError)


def test_team_schema_carries_the_resolved_description():
    def grep(context, pattern: str = ''):
        return 'no matches'

    schema = Tool(tool=grep, name='Grep',
                  description=lambda ctx: f'regex over {ctx.cwd}',
                  parameters={'type': 'object',
                              'properties': {'pattern': {'type': 'string'}}})

    async def main():
        team = mock_team('t', tool_context=CTX, tools=[schema],
                         handler=lambda m, tools=None, *, stream_cb=None: 'done')
        return {t['name']: t['description'] for t in team.tool_schemas(CTX)}

    schemas = asyncio.run(main())
    assert schemas['Grep'] == f'regex over {Path("/tmp/work")}'
