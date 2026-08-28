import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from chatchat import transport


@pytest.fixture
async def fake_session():
    # Build a fake aiohttp session whose post() returns a context manager
    # yielding an async iterator of raw SSE lines (transport does NOT parse).
    lines = [
        b'data: {"id":"c","choices":[{"delta":{"content":"hi"}}]}\n',
        b'data: [DONE]\n',
    ]

    async def fake_aiter():
        for ln in lines:
            yield ln

    resp = MagicMock()
    resp.status = 200
    resp.content = fake_aiter()
    resp.text = AsyncMock(return_value='')

    post_cm = AsyncMock()
    post_cm.__aenter__.return_value = resp

    session = MagicMock()
    session.post.return_value = post_cm
    transport._session = session
    yield session
    transport._session = None


async def test_get_session_is_lazy_and_singleton():
    # before first use there is no session
    assert transport._session is None
    first = transport.get_session()
    assert first is not None
    # subsequent calls return the same session (lazy, not recreated)
    assert transport.get_session() is first
    await transport.close_transport()
    assert transport._session is None
    # after close a new call lazily creates a fresh session
    second = transport.get_session()
    assert second is not None
    assert second is not first
    await transport.close_transport()


async def test_shutdown_closes_lazy_session():
    from chatchat.runtime import get_runtime
    get_runtime()  # no-op if already created, ensures runtime exists
    # session is lazily created on first use
    session = transport.get_session()
    assert session is not None
    await transport.close_transport()
    assert transport._session is None


async def test_stream_yields_raw_sse_lines(fake_session):
    t = transport.Transport(name='t', emit=None)
    out = []
    async for line in t.stream(
        'https://x/v1/chat/completions', {'m': 1}, {'Authorization': 'Bearer k'},
    ):
        out.append(line)
    assert out == [
        '{"id":"c","choices":[{"delta":{"content":"hi"}}]}',
        '[DONE]',
    ]
    # transport performs NO business parsing: it only strips the `data:` prefix
    assert all(not l.startswith('data:') for l in out)


async def test_stream_forwards_full_url_headers_and_proxy_once(fake_session):
    t = transport.Transport(name='t', emit=None)
    async for _ in t.stream(
        'https://x/v1/chat/completions', {'m': 1}, {'Authorization': 'Bearer k'},
        timeout=5, proxy='http://p',
    ):
        pass
    args, kwargs = fake_session.post.call_args
    assert args[0] == 'https://x/v1/chat/completions'
    assert kwargs['headers'] == {'Authorization': 'Bearer k'}
    assert kwargs['json'] == {'m': 1}
    assert kwargs['proxy'] == 'http://p'
    assert kwargs['timeout'] == 5


async def test_stream_raises_api_error_on_4xx(fake_session):
    from chatchat.exceptions import APIError
    import chatchat.transport as tr

    resp = MagicMock()
    resp.status = 400
    resp.text = AsyncMock(return_value='bad')
    cm = AsyncMock()
    cm.__aenter__.return_value = resp
    fake_session.post.return_value = cm

    t = tr.Transport(name='t', emit=None)
    with pytest.raises(APIError):
        async for _ in t.stream('https://x', {}, {}):
            pass
