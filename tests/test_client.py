from chatchat.client import BaseClient, ClientConfig, _RetryableError
from chatchat.exceptions import APIError
from chatchat.types import Message, ToolCall, Delta


def _client():
    return BaseClient(ClientConfig(provider='agnes', model='agnes-2.5-flash', name='t'))


class TestUsage:
    def test_to_chat_completion_chunk_parses_usage(self):
        chunk = _client()._to_chat_completion_chunk({
            'id': '1',
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
            'choices': [],
        })
        assert chunk.usage.total_tokens == 15
        assert chunk.usage.prompt_tokens == 10

    def test_chat_releases_real_usage(self):
        import asyncio
        client = _client()

        class Limiter:
            def __init__(self):
                self.tokens = 0

            async def acquire(self):
                pass

            async def release(self, tokens=0):
                self.tokens = tokens

            async def notify_429(self):
                pass

        limiter = Limiter()
        client._rate_limiter = limiter

        async def fake_post_stream(url, payload):
            yield '{"id":"c","usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5},"choices":[]}'
            yield '[DONE]'

        client._transport.stream = fake_post_stream

        async def run():
            async for _ in client.chat([{'role': 'user', 'content': 'hi'}]):
                pass

        asyncio.run(run())
        assert limiter.tokens == 5
        assert client.latest is not None
        assert len(client.messages) == 2


class TestToDelta:
    def test_maps_content(self):
        delta = _client()._to_delta({'content': 'hi', 'tool_calls': []})
        assert delta.content == 'hi'

    def test_maps_reasoning_content(self):
        delta = _client()._to_delta({'content': '', 'reasoning_content': 'think'})
        assert delta.reasoning_content == 'think'

    def test_maps_tool_calls(self):
        data = {
            'tool_calls': [
                {'index': 0, 'id': 'call_1', 'function': {'name': 'f', 'arguments': '{"x":1}'}},
            ],
        }
        delta = _client()._to_delta(data)
        assert len(delta.tool_calls) == 1
        tc = delta.tool_calls[0]
        assert tc.index == 0
        assert tc.id == 'call_1'
        assert tc.name == 'f'
        assert tc.arguments == '{"x":1}'


class TestMessageAccumulate:
    def test_accumulate_content(self):
        m = Message()
        m.accumulate(Delta(content='hel'))
        m.accumulate(Delta(content='lo'))
        assert m.to_dict() == {'role': 'assistant', 'content': 'hello'}

    def test_accumulate_reasoning_content(self):
        m = Message()
        m.accumulate(Delta(reasoning_content='rea'))
        m.accumulate(Delta(reasoning_content='son'))
        assert m.reasoning_content == 'reason'

    def test_accumulate_tool_calls_by_index(self):
        m = Message()
        m.accumulate(Delta(tool_calls=[ToolCall(index=0, id='c1', name='f', arguments='{"a":')]))
        m.accumulate(Delta(tool_calls=[ToolCall(index=0, arguments='1}')]))
        m.accumulate(Delta(tool_calls=[ToolCall(index=1, id='c2', name='g', arguments='{}')]))
        d = m.to_dict()
        assert len(d['tool_calls']) == 2
        first = d['tool_calls'][0]
        assert first['id'] == 'c1'
        assert first['type'] == 'function'
        assert first['function']['name'] == 'f'
        assert first['function']['arguments'] == '{"a":1}'
        assert d['tool_calls'][1]['function']['name'] == 'g'

    def test_to_dict_without_tool_calls_omits_key(self):
        m = Message()
        m.accumulate(Delta(content='hi'))
        assert 'tool_calls' not in m.to_dict()


class TestSendStreamingRetry:
    def test_retries_transient_then_succeeds(self):
        import asyncio
        client = _client()
        client.retry_backoff = 0.01
        calls = {'n': 0}

        async def fake_post_stream(url, payload):
            calls['n'] += 1
            if calls['n'] < 3:
                raise _RetryableError('boom')
            yield 'data: {"id":"1"}'

        client._transport.stream = fake_post_stream

        async def run():
            out = []
            async for line in client._send_streaming('/chat/completions', {}):
                out.append(line)
            return out

        assert asyncio.run(run()) == ['data: {"id":"1"}']
        assert calls['n'] == 3

    def test_no_retry_after_stream_started(self):
        import asyncio
        client = _client()
        calls = {'n': 0}

        async def fake_post_stream(url, payload):
            calls['n'] += 1
            yield 'data: {"id":"1"}'
            raise _RetryableError('boom')

        client._transport.stream = fake_post_stream

        async def run():
            async for _ in client._send_streaming('/chat/completions', {}):
                pass

        try:
            asyncio.run(run())
            raise AssertionError('expected APIError')
        except APIError as e:
            assert 'boom' in str(e)
        assert calls['n'] == 1

    def test_exhausts_retries_raises_api_error(self):
        import asyncio
        client = _client()
        client.max_retries = 2
        client.retry_backoff = 0.01
        calls = {'n': 0}

        async def fake_post_stream(url, payload):
            calls['n'] += 1
            if False:
                yield ''
            raise _RetryableError('boom')

        client._transport.stream = fake_post_stream

        async def run():
            async for _ in client._send_streaming('/chat/completions', {}):
                pass

        try:
            asyncio.run(run())
            raise AssertionError('expected APIError')
        except APIError as e:
            assert 'API request failed' in str(e)
        assert calls['n'] == client.max_retries + 1
