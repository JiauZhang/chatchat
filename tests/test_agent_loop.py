import asyncio

from chatchat.agent_loop import AgentLoop
from chatchat.tool import Tools
from chatchat.types import Message, ToolCall, Delta
from chatchat.runtime import set_runtime


class _FakeClient:
    """Mimics BaseClient.chat: accumulates `messages`, appending whatever is
    handed in plus its own assistant reply. Records the full payload sent."""

    def __init__(self, replies):
        self.messages = []
        self.latest = None
        self.latest_usage = None
        self._replies = list(replies)
        self._payloads = []

    async def chat(self, messages, *, model=None, thinking=False, tools=None, **kwargs):
        full = self.messages + messages
        self.latest = self._replies.pop(0)
        self.messages = full + [self.latest.to_dict()]
        self._payloads.append(full)
        yield self.latest


def _assistant(*tool_calls):
    m = Message()
    if tool_calls:
        m.accumulate(Delta(tool_calls=[
            ToolCall(index=i, id=f'call_{i}', name=n, arguments='{}')
            for i, n in enumerate(tool_calls)
        ]))
    else:
        m.accumulate(Delta(content='done'))
    return m


class _ToolRuntime:
    async def publish(self, ev):
        return None

    async def request(self, **kwargs):
        return {'role': 'tool', 'content': 'ok',
                'tool_call_id': kwargs['data']['tool_call_id']}


async def _run(replies):
    import chatchat.agent_loop as al
    client = _FakeClient(replies)
    loop = AgentLoop(client, Tools(), max_steps=5, thinking=False, name='a',
                     agent=None, allowed_tools={'roll'})
    original_rt, original_start = al.get_runtime, al.start_tool_handler
    al.get_runtime = lambda: _ToolRuntime()
    al.start_tool_handler = lambda: None
    try:
        result = await loop.run('start', context=[])
    finally:
        al.get_runtime, al.start_tool_handler = original_rt, original_start
    return result, client


def _assert_valid_tool_pairs(messages):
    pending = 0
    for m in messages:
        if m.get('tool_calls'):
            pending = len(m['tool_calls'])
        elif m['role'] == 'tool':
            assert pending > 0, f'tool message without preceding tool_calls: {messages}'
            pending -= 1
    assert pending == 0, f'unanswered tool_calls: {messages}'
    return True


class TestAgentLoopMessageAssembly:
    def test_single_tool_roundtrip(self):
        result, client = asyncio.run(_run([_assistant('roll'), _assistant()]))

        assert result == 'done'
        assert client._payloads[0] == [{'role': 'user', 'content': 'start'}]
        assert client._payloads[1] == [
            {'role': 'user', 'content': 'start'},
            _assistant('roll').to_dict(),
            {'role': 'tool', 'content': 'ok', 'tool_call_id': 'call_0'},
        ]
        assert _assert_valid_tool_pairs(client._payloads[1])
        set_runtime(None)

    def test_multi_turn_no_duplicate_history(self):
        result, client = asyncio.run(
            _run([_assistant('roll'), _assistant('roll'), _assistant()])
        )

        assert result == 'done'
        # turn 3 must contain exactly 5 messages, no duplicated user/assistant
        assert len(client._payloads[2]) == 5
        assert [m['role'] for m in client._payloads[2]] == [
            'user', 'assistant', 'tool', 'assistant', 'tool',
        ]
        assert _assert_valid_tool_pairs(client._payloads[2])
        set_runtime(None)

    def test_parallel_tool_calls_all_get_results(self):
        result, client = asyncio.run(
            _run([_assistant('roll', 'roll'), _assistant()])
        )

        assert result == 'done'
        assert [m['role'] for m in client._payloads[1]] == [
            'user', 'assistant', 'tool', 'tool',
        ]
        assert _assert_valid_tool_pairs(client._payloads[1])
        set_runtime(None)
