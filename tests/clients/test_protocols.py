import json

import pytest

from chatchat.runtime.thinking import Thinking
from chatchat.protocols import get_protocol
from chatchat.protocols.anthropic import parse as a_parse
from chatchat.protocols.openai import parse as o_parse
from chatchat.protocols.openai import to_openai


USER_TOOL_RESULT = [
    {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'sunny'},
    {'type': 'text', 'text': 'context'},
]
ASSISTANT_TOOL_USE = [
    {'type': 'tool_use', 'id': 't1', 'name': 'weather',
     'input': {'city': 'Beijing'}},
]
TOOLS = [{'name': 'weather', 'description': 'look up weather',
          'input_schema': {'type': 'object',
                           'properties': {'city': {'type': 'string'}}}}]


def test_openai_payload_keeps_the_stream_and_thinking_shape():
    body = get_protocol('openai').payload(
        [{'role': 'user', 'content': 'hi'}], None, 'm1', Thinking('off'))
    assert body['model'] == 'm1'
    assert body['stream'] is True
    assert body['stream_options'] == {'include_usage': True}
    assert body['thinking'] == {'type': 'disabled'}


def test_openai_payload_converts_tools_to_function_schemas():
    body = get_protocol('openai').payload([], TOOLS, 'm1', Thinking('off'))
    assert body['tools'][0]['type'] == 'function'
    assert body['tools'][0]['function']['parameters']['properties'] == \
        {'city': {'type': 'string'}}


def test_openai_endpoint_and_headers():
    protocol = get_protocol('openai')
    assert protocol.endpoint('https://api.example.com/v1') == \
        'https://api.example.com/v1/chat/completions'
    assert protocol.headers('sk-1')['Authorization'] == 'Bearer sk-1'


def test_openai_parse_reads_text_and_usage():
    usage, deltas = o_parse(b'data: ' + json.dumps({
        'choices': [{'delta': {'content': 'hello'}}],
        'usage': {'prompt_tokens': 5, 'completion_tokens': 2,
                  'total_tokens': 7}}).encode())
    assert deltas[0].content == 'hello'
    assert usage['prompt_tokens'] == 5


def test_openai_parse_skips_noise():
    assert o_parse(b'') == (None, [])
    assert o_parse(b'data: [DONE]') == (None, [])
    assert o_parse(b'not json') == (None, [])


def test_anthropic_extracts_system_and_requires_max_tokens():
    messages = [{'role': 'system', 'content': 'be brief'},
                {'role': 'user', 'content': 'hi'}]
    body = get_protocol('anthropic').payload(messages, None, 'm1', Thinking('off'))
    assert body['system'] == 'be brief'
    assert body['messages'] == [{'role': 'user', 'content': 'hi'}]
    assert body['max_tokens'] > 0
    assert body['stream'] is True


def test_anthropic_tools_pass_through_with_input_schema():
    body = get_protocol('anthropic').payload([], TOOLS, 'm1', Thinking('off'))
    assert body['tools'][0] == {'name': 'weather',
                                'description': 'look up weather',
                                'input_schema': {'type': 'object',
                                                 'properties': {
                                                     'city': {'type': 'string'}}}}


def test_anthropic_internal_blocks_go_through_verbatim():
    messages = [{'role': 'assistant', 'content': ASSISTANT_TOOL_USE},
                {'role': 'user', 'content': USER_TOOL_RESULT}]
    body = get_protocol('anthropic').payload(messages, None, 'm1', Thinking('off'))
    assert body['messages'][0]['content'][0]['type'] == 'tool_use'
    assert body['messages'][0]['content'][0]['input'] == {'city': 'Beijing'}
    assert body['messages'][1]['content'][0]['type'] == 'tool_result'
    assert body['messages'][1]['content'][0]['tool_use_id'] == 't1'


def test_anthropic_endpoint_headers_and_parse_noise():
    protocol = get_protocol('anthropic')
    assert protocol.endpoint('https://api.anthropic.com') == \
        'https://api.anthropic.com/v1/messages'
    assert protocol.headers('sk-a')['x-api-key'] == 'sk-a'
    assert protocol.headers('sk-a')['anthropic-version']
    assert a_parse(b'event: ping') == (None, [])
    assert a_parse(b'data: {"type":"content_block_stop"}') == (None, [])


def _sse(obj):
    return b'data: ' + json.dumps(obj).encode()


def test_anthropic_parse_streams_text_thinking_and_tool_use():
    usage1, deltas = a_parse(_sse({
        'type': 'message_start',
        'message': {'usage': {'input_tokens': 100,
                              'cache_read_input_tokens': 80}}}))
    assert usage1['prompt_tokens'] == 100
    assert usage1['prompt_tokens_details'] == {'cached_tokens': 80}
    _, deltas = a_parse(_sse({
        'type': 'content_block_start', 'index': 1,
        'content_block': {'type': 'tool_use', 'id': 't1',
                          'name': 'weather'}}))
    assert deltas[0].tool_calls[0].name == 'weather'
    assert deltas[0].tool_calls[0].index == 1
    _, deltas = a_parse(_sse({
        'type': 'content_block_delta', 'index': 0,
        'delta': {'type': 'thinking_delta', 'thinking': 'hmm'}}))
    assert deltas[0].reasoning_content == 'hmm'
    _, deltas = a_parse(_sse({
        'type': 'content_block_delta', 'index': 0,
        'delta': {'type': 'text_delta', 'text': 'hi'}}))
    assert deltas[0].content == 'hi'
    _, deltas = a_parse(_sse({
        'type': 'content_block_delta', 'index': 1,
        'delta': {'type': 'input_json_delta', 'partial_json': '{"city"'}}))
    assert deltas[0].tool_calls[0].arguments == '{"city"'
    usage2, _ = a_parse(_sse({
        'type': 'message_delta', 'usage': {'output_tokens': 21}}))
    assert usage2['completion_tokens'] == 21


def test_anthropic_thinking_request_shares_the_reference_shape():
    body = get_protocol('anthropic').payload(
        [{'role': 'user', 'content': 'hi'}], None, 'm1',
        Thinking('on', budget=8000))
    assert body['thinking'] == {'type': 'enabled', 'budget_tokens': 8000}


def test_get_protocol_refuses_unknown_types():
    with pytest.raises(ValueError):
        get_protocol('grpc')


def test_openai_protocol_maps_tool_flow_exactly_as_before():
    messages = [{'role': 'user', 'content': 'weather?'},
                {'role': 'assistant', 'content': ASSISTANT_TOOL_USE},
                {'role': 'user', 'content': USER_TOOL_RESULT}]
    out = to_openai(messages)
    assert out[1]['tool_calls'][0]['function']['name'] == 'weather'
    assert out[2] == {'role': 'tool', 'tool_call_id': 't1',
                      'content': 'sunny'}
