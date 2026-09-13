import asyncio

from chatchat.client import MockClient, ToolUse
from chatchat.core.inbox_poller import InboxPoller
from chatchat.core.mailbox import Mailbox
from chatchat.hooks.events import AGENT_TOOL_CALL, clear_runtime_sinks, \
    register_runtime_handler
from chatchat.team import Team

LEAD = ('你是 team lead。把任务拆开用 send_message 发给 teammate 并等回信，'
        '最后汇总最终答案。')
RESEARCHER = '你是 researcher。收到任务后用 send_message 回研究结论，然后结束。'


def make_team():
    async def lead_respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'lead 最终汇总：researcher 已研究完成。'
        return [ToolUse('send_message', {'to': 'researcher',
                                         'message': '调研 DeepSeek'}, 'm1')]

    async def researcher_respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return '我是 researcher，已回信。'
        return [ToolUse('send_message', {'to': 'team-lead',
                                         'message': '结论：DeepSeek 优秀'}, 'm2')]

    def factory(instruction):
        if 'researcher' in instruction:
            return MockClient(handler=researcher_respond)
        return MockClient(handler=lead_respond)

    return Team('demo', client_factory=factory, lead_instruction=LEAD)


def test_team_send_message_flow_and_tool_event():
    events = []
    clear_runtime_sinks()
    register_runtime_handler(lambda ev: events.append(ev.kind))

    async def main():
        team = make_team()
        team.create_agent('researcher', instruction=RESEARCHER)
        answer = await team.query('调研一下 DeepSeek', timeout=15)
        return answer

    answer = asyncio.run(main())
    assert '汇总' in answer
    assert AGENT_TOOL_CALL in events


def test_wait_idle_not_satisfied_by_stale_idle_set():
    async def respond(messages, tools=None, *, stream_cb=None):
        await asyncio.sleep(0.3)
        return 'ok'

    async def main():
        team = Team('race', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.submit('new')
        lead._set_idle()
        try:
            await asyncio.wait_for(lead.wait_idle(), 0.05)
            return 'early'
        except asyncio.TimeoutError:
            return 'waited'
        finally:
            await asyncio.wait_for(lead.wait_idle(), 1.0)

    assert asyncio.run(main()) == 'waited'


def test_interrupt_and_submit_aborts_running_cancelable_tool():
    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        return [ToolUse('sleep_long', {}, 's1')]

    async def sleep_long(**kw):
        await asyncio.sleep(10)

    async def main():
        team = Team('int', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.submit('start')
        lead._in_tool = 'sleep_long'
        lead.interrupt_and_submit('new msg', cancelable_tools=('sleep_long',))
        interrupted = lead._work_abort.aborted
        try:
            await asyncio.wait_for(lead.wait_idle(), 1.5)
        except asyncio.TimeoutError:
            pass
        return interrupted

    assert asyncio.run(main()) is True


def test_interrupt_and_submit_queues_for_non_cancelable_tool():
    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        return [ToolUse('bash', {}, 'b1')]

    async def main():
        team = Team('int2', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.submit('start')
        lead._in_tool = 'bash'
        lead.interrupt_and_submit('new', cancelable_tools=('sleep_long',))
        interrupted = lead._work_abort.aborted
        try:
            await asyncio.wait_for(lead.wait_idle(), 1.5)
        except asyncio.TimeoutError:
            pass
        return interrupted

    assert asyncio.run(main()) is False


def test_report_surfaces_when_lead_never_writes_text():
    LEAD_INST = 'LEAD_PROMPT'
    report = '# DeepSeek 综合研究报告\nDeepSeek 是深度求索。'

    async def lead_respond(messages, tools=None, *, stream_cb=None):
        return [ToolUse('create_agent', {'prompt': '再细化'}, 'd1')]

    async def sub_respond(messages, tools=None, *, stream_cb=None):
        return report

    def factory(instruction):
        return MockClient(handler=lead_respond if instruction == LEAD_INST
                          else sub_respond)

    async def main():
        team = Team('rep', client_factory=factory, lead_instruction=LEAD_INST,
                    max_steps=3)
        ans = await team.query('给我一份 deepseek 报告', timeout=15)
        return ans

    ans = asyncio.run(main())
    assert 'DeepSeek 综合' in ans
    assert not ans.startswith('Error')


def test_inbox_frame_is_counted_as_pending():
    async def main():
        release = asyncio.Event()

        async def respond(messages, tools=None, *, stream_cb=None):
            await release.wait()
            return 'ok'

        team = Team('inbox', client_factory=lambda inst: MockClient(
            handler=respond))
        lead = team.lead
        lead.inbox.write('peer@inbox', 'hello from peer')
        await lead.poll_inbox()
        assert lead._pending == 1
        assert lead._done == 0
        try:
            await asyncio.wait_for(lead.wait_idle(), 0.05)
            early = True
        except asyncio.TimeoutError:
            early = False
        release.set()
        await asyncio.wait_for(lead.wait_idle(), 2.0)
        return early

    assert asyncio.run(main()) is False


def test_inbox_poller_reports_enqueue_to_callback():
    async def main():
        inbox = Mailbox()
        queue = asyncio.Queue()
        bumps = []
        poller = InboxPoller(inbox, queue, interval=0.01,
                             on_enqueue=lambda: bumps.append(1))
        poller.start()
        inbox.write('peer@x', 'hi')
        await asyncio.sleep(0.06)
        await poller.stop()
        return len(bumps), queue.qsize()

    bumps, queued = asyncio.run(main())
    assert bumps >= 1
    assert queued >= 1
