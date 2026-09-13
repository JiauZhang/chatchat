from chatchat.client import MockClient, Usage, ToolUse
from chatchat.core.team import Team


def test_usage_from_dict_and_add():
    a = Usage.from_dict({'prompt_tokens': 285, 'completion_tokens': 55,
                         'total_tokens': 340,
                         'prompt_tokens_details': {'cached_tokens': 256}})
    b = Usage.from_dict({'prompt_tokens': 10, 'completion_tokens': 20,
                         'total_tokens': 30,
                         'prompt_tokens_details': {'cached_tokens': 5}})
    a.add(b)
    assert a.prompt_tokens == 295
    assert a.completion_tokens == 75
    assert a.total_tokens == 370
    assert a.prompt_tokens_details == {'cached_tokens': 261}


def test_usage_from_dict_none_keeps_zeros():
    u = Usage.from_dict(None)
    assert u.prompt_tokens == 0
    assert u.completion_tokens == 0
    assert u.total_tokens == 0
    assert u.prompt_tokens_details is None


def test_team_query_accumulates_usage():
    async def respond(messages, tools=None, *, stream_cb=None):
        return 'done'
    factory = lambda inst: MockClient(handler=respond, usage={
        'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
        'prompt_tokens_details': {'cached_tokens': 80}})

    async def main():
        team = Team('u', client_factory=factory)
        await team.query('hi')
        await team.query('again')
        return team.usage()

    usage = asyncio_run(main())
    assert usage.prompt_tokens == 200
    assert usage.completion_tokens == 40
    assert usage.total_tokens == 240
    assert usage.prompt_tokens_details['cached_tokens'] == 160


def test_provider_without_usage_keeps_zeros():
    factory = lambda inst: MockClient(handler=lambda m, t=None, **k: 'ok')

    async def main():
        team = Team('u', client_factory=factory)
        await team.query('hi')
        return team.usage()

    usage = asyncio_run(main())
    assert usage.total_tokens == 0
    assert usage.prompt_tokens_details is None


def test_thinking_stored_on_assistant_message():
    def respond(messages, tools=None, *, stream_cb=None):
        if stream_cb:
            stream_cb('让我想想。', 'reason')
            stream_cb('先看天气。', 'reason')
            stream_cb('好的。', 'text')
        return '看好了'

    async def main():
        team = Team('t', client_factory=lambda inst: MockClient(handler=respond))
        await team.query('现在天气如何')
        return team.transcript()

    msgs = asyncio_run(main())
    assistant = next(m for m in msgs if m.get('role') == 'assistant')
    assert assistant['thinking'] == '让我想想。先看天气。'
    assert assistant['content'] == '看好了'


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def _payload_for(monkeypatch, thinking: bool) -> dict:
    import chatchat.client as client_mod
    from chatchat.client import Client

    captured = {}

    class FakeResp:
        def __init__(self):
            self.content = self._lines()

        @property
        def status(self):
            return 200

        def raise_for_status(self):
            pass

        async def _lines(self):
            yield b'data: [DONE]\n'
            return

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def fake_post(*args, **kw):
        captured['payload'] = kw.get('json', {})
        return FakeResp()

    monkeypatch.setattr(client_mod.aiohttp.ClientSession, 'post', fake_post)
    c = Client.__new__(Client)
    c.provider = 'deepseek'
    c.model = 'deepseek-flash'
    c.thinking = thinking
    c.instruction = None
    c.base_url = 'https://api.deepseek.com'
    c.api_key = 'x'
    c._headers = {}
    c._timeout = client_mod.aiohttp.ClientTimeout(total=30)
    c._last_usage = Usage()
    asyncio_run(c.respond([{'role': 'user', 'content': 'hi'}]))
    return captured['payload']


def test_respond_payload_thinking_explicit_disabled(monkeypatch):
    assert _payload_for(monkeypatch, False)['thinking'] == {'type': 'disabled'}


def test_respond_payload_thinking_default_enabled(monkeypatch):
    assert _payload_for(monkeypatch, True)['thinking'] == {'type': 'enabled'}
