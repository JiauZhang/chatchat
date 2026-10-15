import asyncio
from pathlib import Path

from chatchat.protocols.anthropic import payload as a_payload
from chatchat.protocols.openai import payload as o_payload
from chatchat.runtime.thinking import Thinking
from chatchat.runtime.tokens import rough
from chatchat.tool import Tool, ToolContext, ToolResult
from helpers import mock_team

PNG = {'type': 'image',
       'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aGk='}}
TOOL_USE = [{'type': 'tool_use', 'id': 't1', 'name': 'shot', 'input': {}}]


def test_openai_user_image_becomes_a_content_part():
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'what is this?'},
        PNG,
    ]}]
    body = o_payload(messages, None, 'm1', Thinking('off'))
    assert body['input'][0]['content'] == [
        {'type': 'input_text', 'text': 'what is this?'},
        {'type': 'input_image', 'image_url': 'data:image/png;base64,aGk='},
    ]


def test_openai_tool_result_images_ride_the_function_output():
    messages = [{'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't1', 'content': [
            {'type': 'text', 'text': 'captured'},
            PNG,
        ]},
    ]}]
    body = o_payload(messages, None, 'm1', Thinking('off'))
    assert body['input'][0] == {'type': 'function_call_output',
                                'call_id': 't1',
                                'output': [{'type': 'input_text',
                                            'text': 'captured'},
                                           {'type': 'input_image',
                                            'image_url': 'data:image/png;base64,aGk='}]}



def test_anthropic_passes_image_blocks_through_verbatim():
    messages = [{'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't1', 'content': [
            {'type': 'text', 'text': 'captured'}, PNG,
        ]},
    ]}]
    body = a_payload(messages, None, 'm1', Thinking('off'))
    assert body['messages'][0]['content'][0]['content'] == [
        {'type': 'text', 'text': 'captured'}, PNG]


def test_an_image_block_costs_a_fixed_token_budget():
    text_only = rough({'content': 'x' * 40})
    with_image = rough({'content': [
        {'type': 'text', 'text': 'x' * 40},
        PNG,
    ]})
    assert with_image > text_only
    assert with_image - text_only >= 800


def test_a_tool_result_combines_text_and_image_blocks():
    from chatchat.client import ToolUse

    tool = Tool(tool=lambda ctx, **kw: ToolResult(
        text='screenshot saved', blocks=[PNG]),
        name='Shot', description='takes a screenshot')

    def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return '看到了。'
        return [ToolUse('Shot', {}, 't1')]

    async def main():
        team = mock_team('shot', tools=[tool], handler=respond)
        await team.query('look')
        return team.transcript()

    msgs = asyncio.run(main())
    tool_result = next(m for m in msgs if isinstance(m.get('content'), list)
                       and any(isinstance(b, dict)
                               and b.get('type') == 'tool_result'
                               for b in m['content']))
    block = tool_result['content'][0]
    assert block['tool_use_id'] == 't1'
    assert block['content'][0] == {'type': 'text', 'text': 'screenshot saved'}
    assert block['content'][1] == PNG
