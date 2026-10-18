import json

import pytest

from chatchat.runtime.thinking import Thinking
from chatchat.protocols.anthropic import payload as a_payload
from chatchat.protocols.anthropic import parse as a_parse
from chatchat.protocols.openai import parse as o_parse, payload as o_payload
from chatchat.protocols.openai import endpoint, headers, input_items
from chatchat.protocols.anthropic import endpoint as a_endpoint
from chatchat.protocols.anthropic import headers as a_headers
from chatchat.protocols import get_protocol

USER_TOOL_RESULT = [
    {"type": "tool_result", "tool_use_id": "t1", "content": "sunny"},
    {"type": "text", "text": "context"},
]
ASSISTANT_TOOL_USE = [
    {"type": "tool_use", "id": "t1", "name": "weather", "input": {"city": "Beijing"}},
]
TOOLS = [
    {
        "name": "weather",
        "description": "look up weather",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
    }
]
REASONING_ITEM = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc"}


def _sse(obj):
    return b"data: " + json.dumps(obj).encode()


def test_openai_endpoint_and_headers():
    assert endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/responses"
    assert headers("sk-1")["Authorization"] == "Bearer sk-1"


def test_openai_payload_uses_instructions_for_system():
    messages = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    body = o_payload(messages, None, "m1", Thinking("off"))
    assert body["instructions"] == "be brief"
    assert body["input"] == [{"role": "user", "content": "hi"}]
    assert body["stream"] is True and body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert "reasoning" not in body and "thinking" not in body


def test_openai_payload_converts_the_tool_flow():
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": ASSISTANT_TOOL_USE},
        {"role": "user", "content": USER_TOOL_RESULT},
    ]
    body = o_payload(messages, TOOLS, "m1", Thinking("off"))
    assert body["input"][1] == {
        "type": "function_call",
        "id": "fc_t1",
        "call_id": "t1",
        "name": "weather",
        "arguments": '{"city": "Beijing"}',
    }
    assert body["input"][2] == {"type": "function_call_output", "call_id": "t1", "output": "sunny"}
    assert body["input"][3] == {"role": "user", "content": [{"type": "input_text", "text": "context"}]}
    assert body["tools"] == [
        {
            "type": "function",
            "name": "weather",
            "description": "look up weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]


def test_openai_replays_the_response_output_verbatim():
    """The saved output items (reasoning, function_call with both ids) go back
    exactly as the API emitted them; nothing is re-synthesised on top."""
    fc = {"type": "function_call", "id": "fc_1", "call_id": "t1", "name": "weather", "arguments": '{"city": "Beijing"}'}
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": ASSISTANT_TOOL_USE, "response_items": [REASONING_ITEM, fc]},
    ]
    body = o_payload(messages, None, "m1", Thinking("off"))
    assert body["input"][1] == REASONING_ITEM
    assert body["input"][2] == fc
    assert len(body["input"]) == 3


def test_openai_synthesises_function_calls_without_saved_output():
    messages = [{"role": "user", "content": "weather?"}, {"role": "assistant", "content": ASSISTANT_TOOL_USE}]
    body = o_payload(messages, None, "m1", Thinking("off"))
    assert body["input"][1] == {
        "type": "function_call",
        "id": "fc_t1",
        "call_id": "t1",
        "name": "weather",
        "arguments": '{"city": "Beijing"}',
    }


def test_openai_user_image_becomes_an_input_image_part():
    png = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "what is this?"}, png]}]
    body = o_payload(messages, None, "m1", Thinking("off"))
    assert body["input"][0]["content"] == [
        {"type": "input_text", "text": "what is this?"},
        {"type": "input_image", "image_url": "data:image/png;base64,aGk="},
    ]


def test_openai_tool_result_images_ride_the_output_array():
    png = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}}
    messages = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "captured"}, png]}],
        }
    ]
    body = o_payload(messages, None, "m1", Thinking("off"))
    assert body["input"][0] == {
        "type": "function_call_output",
        "call_id": "t1",
        "output": [
            {"type": "input_text", "text": "captured"},
            {"type": "input_image", "image_url": "data:image/png;base64,aGk="},
        ],
    }


def test_openai_effort_maps_to_the_reasoning_field():
    messages = [{"role": "user", "content": "hi"}]
    body = o_payload(messages, None, "m1", Thinking("high"))
    assert body["reasoning"] == {"effort": "high"}
    assert "reasoning" not in o_payload(messages, None, "m1", Thinking("off"))


def test_openai_parse_reads_text_usage_and_response():
    usage, deltas, response = o_parse(_sse({"type": "response.output_text.delta", "delta": "hello"}))
    assert deltas[0].content == "hello"
    usage, _, response = o_parse(
        _sse(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [{"type": "reasoning", "id": "rs_1"}],
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 2,
                        "total_tokens": 7,
                        "input_tokens_details": {"cached_tokens": 3},
                    },
                },
            }
        )
    )
    assert response["id"] == "resp_1"
    assert usage["prompt_tokens"] == 5
    assert usage["prompt_tokens_details"] == {"cached_tokens": 3}


def test_openai_parse_streams_tool_calls_and_reasoning():
    usage, deltas, _ = o_parse(
        _sse(
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {"type": "function_call", "call_id": "call_1", "name": "weather"},
            }
        )
    )
    assert deltas[0].tool_calls[0].index == 1
    assert deltas[0].tool_calls[0].name == "weather"
    _, deltas, _ = o_parse(_sse({"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"city"'}))
    assert deltas[0].tool_calls[0].arguments == '{"city"'
    _, deltas, _ = o_parse(_sse({"type": "response.reasoning_summary_text.delta", "delta": "hmm"}))
    assert deltas[0].reasoning_content == "hmm"
    _, deltas, _ = o_parse(
        _sse({"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning", "id": "rs_1"}})
    )
    assert deltas == []


def test_openai_parse_skips_noise():
    assert o_parse(b"") == (None, [], None)
    assert o_parse(b"event: ping") == (None, [], None)


def test_input_items_replays_plain_assistant_text_as_output_text():
    items = input_items([{"role": "assistant", "content": "earlier answer"}])
    assert items == [{"role": "assistant", "content": [{"type": "output_text", "text": "earlier answer"}]}]


def test_anthropic_extracts_system_and_requires_max_tokens():
    messages = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    body = a_payload(messages, None, "m1", Thinking("off"))
    assert body["system"] == "be brief"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_tokens"] > 0
    assert body["stream"] is True


def test_anthropic_internal_blocks_go_through_verbatim():
    messages = [{"role": "assistant", "content": ASSISTANT_TOOL_USE}, {"role": "user", "content": USER_TOOL_RESULT}]
    body = a_payload(messages, None, "m1", Thinking("off"))
    assert body["messages"][0]["content"][0]["type"] == "tool_use"
    assert body["messages"][1]["content"][0]["type"] == "tool_result"
    assert body["messages"][1]["content"][0]["tool_use_id"] == "t1"


def test_anthropic_parse_streams_text_thinking_and_tool_use():

    assert a_endpoint("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    assert a_headers("sk-a")["x-api-key"] == "sk-a"
    usage1, deltas, _ = a_parse(
        _sse({"type": "message_start", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 80}}})
    )
    assert usage1["prompt_tokens"] == 100
    assert usage1["prompt_tokens_details"] == {"cached_tokens": 80}
    _, deltas, _ = a_parse(
        _sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "weather"}})
    )
    assert deltas[0].tool_calls[0].name == "weather"
    _, deltas, _ = a_parse(
        _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}})
    )
    assert deltas[0].reasoning_content == "hmm"
    _, deltas, _ = a_parse(_sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}))
    assert deltas[0].content == "hi"
    usage2, _, _ = a_parse(_sse({"type": "message_delta", "usage": {"output_tokens": 21}}))
    assert usage2["completion_tokens"] == 21
    assert a_parse(b"event: ping") == (None, [], None)


def test_anthropic_thinking_request_shares_the_reference_shape():
    body = a_payload([{"role": "user", "content": "hi"}], None, "m1", Thinking("high"))
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}


def test_get_protocol_refuses_unknown_types():

    with pytest.raises(ValueError):
        get_protocol("grpc")
