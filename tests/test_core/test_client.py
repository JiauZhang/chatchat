import asyncio

import chatchat.client as client_mod
from chatchat.core.thinking import Thinking
from chatchat.client import Client, Usage
from helpers import mock_team


def test_thinking_stored_on_assistant_message():
    def respond(messages, tools=None, *, stream_cb=None):
        if stream_cb:
            stream_cb('让我想想。', 'reason')
            stream_cb('先看天气。', 'reason')
            stream_cb('好的。', 'text')
        return '看好了'

    async def main():
        team = mock_team('t', handler=respond)
        await team.query('现在天气如何')
        return team.transcript()

    msgs = asyncio.run(main())
    assistant = next(m for m in msgs if m.get('role') == 'assistant')
    assert assistant['thinking'] == '让我想想。先看天气。'
    assert assistant['content'] == '看好了'


def test_the_model_that_answered_is_recorded_on_the_message():
    async def main():
        team = mock_team('t', handler=lambda messages, tools=None,
                         *, stream_cb=None: '好的')
        team.lead.client.model = 'mock-model'
        await team.query('hi')
        return team.transcript()

    msgs = asyncio.run(main())
    assistant = next(m for m in msgs if m.get('role') == 'assistant')
    assert assistant['model'] == 'mock-model'


def _payload_for(monkeypatch, thinking) -> dict:
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
    asyncio.run(c.respond([{'role': 'user', 'content': 'hi'}]))
    return captured['payload']


def test_respond_payload_carries_the_thinking_setting(monkeypatch):
    for thinking, expected in ((Thinking('off'), 'disabled'),
                               (Thinking(), 'enabled')):
        assert _payload_for(monkeypatch, thinking)['thinking'] == {
            'type': expected}
    budgeted = _payload_for(monkeypatch, Thinking('on', budget=8000))
    assert budgeted['thinking'] == {'type': 'enabled', 'budget_tokens': 8000}
    effort = _payload_for(monkeypatch, Thinking(effort='high'))
    assert effort['reasoning_effort'] == 'high'
    assert 'reasoning_effort' not in _payload_for(monkeypatch,
                                                  Thinking('off'))


def test_the_mock_client_answers_the_model_question_a_real_one_answers():
    """Displays ask an agent which model it is talking to; the double has to
    carry it or that read only works in production."""
    async def main():
        team = mock_team('models')
        return team, team.create_agent('researcher', model='cheap-m')

    team, researcher = asyncio.run(main())
    assert researcher.client.model == 'cheap-m'
    assert team.lead.client.model is None
