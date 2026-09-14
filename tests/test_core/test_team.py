import asyncio

from chatchat.client import MockClient, ToolUse
from chatchat.core.inbox_poller import InboxPoller
from chatchat.core.mailbox import Mailbox
from chatchat.hooks.events import AGENT_TOOL_CALL, AGENT_WARN, \
    clear_runtime_sinks, register_runtime_handler
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


def _notification_texts(messages):
    return [m['content'] for m in messages if m['role'] == 'user'
            and isinstance(m.get('content'), str)
            and 'task-notification' in m['content']]


def test_attachment_injected_before_next_model_call():
    """turn 开始前入队的附件必须在第一次模型调用前注入，且只注入一次。"""
    payloads = []

    async def respond(messages, tools=None, *, stream_cb=None):
        payloads.append(_notification_texts(messages))
        return 'ok'

    async def main():
        team = Team('att', client_factory=lambda inst: MockClient(handler=respond))
        team.lead.enqueue_attachment('<task-notification>b1</task-notification>')
        return await team.query('go')

    asyncio.run(main())
    assert len(payloads) == 1
    assert len(payloads[0]) == 1


def test_attachment_enqueued_mid_turn_reaches_next_model_call():
    """turn 进行中（工具执行后）入队的附件要在下一次模型调用前注入。"""
    holder = {}
    payloads = []

    async def respond(messages, tools=None, *, stream_cb=None):
        payloads.append(_notification_texts(messages))
        if len(payloads) == 1:
            holder['lead'].enqueue_attachment(
                '<task-notification>b1</task-notification>')
            return [ToolUse('whatever', {}, 't1')]
        return 'done'

    async def main():
        team = Team('att2', client_factory=lambda inst: MockClient(handler=respond))
        holder['lead'] = team.lead
        return await team.query('go')

    asyncio.run(main())
    assert len(payloads) >= 2
    assert len(payloads[0]) == 0       # 第一轮调用时还没有
    assert len(payloads[1]) == 1       # 工具结果后、第二次调用前已注入
    assert all(len(p) == 1 for p in payloads[1:])   # 不重复注入


def test_tool_schemas_differ_by_multi_agent():
    """对齐 claude：协作工具（send_message/task_stop）只在 multi_agent=True 的
    team 出现；一次性 subagent（create_agent）两种模式都有（claude 常态能力）。"""
    async def names(**kw):
        team = Team('m', client_factory=lambda inst: MockClient(handler=_ok), **kw)
        return {t['name'] for t in team.tool_schemas()}

    async def _ok(messages, tools=None, *, stream_cb=None):
        return 'ok'

    single = asyncio.run(names(multi_agent=False))
    multi = asyncio.run(names())
    assert 'create_agent' in single and 'create_agent' in multi
    assert 'send_message' not in single and 'task_stop' not in single
    assert {'send_message', 'task_stop'} <= multi


def test_model_timeout_is_visible_and_query_never_returns_stale_text():
    """回归：模型调用超时的错误只进 messages 不 emit → 外壳一片空白；
    query 超时返回 last_assistant 会捞到上一轮的旧文（含上一轮的超时错误）。
    对齐：超时必须 AGENT_WARN 可见；query 只返回本轮切片内的助手文本。"""
    events = []
    register_runtime_handler(lambda ev: events.append(ev))

    async def respond(messages, tools=None, *, stream_cb=None):
        await asyncio.sleep(2)          # 远超 model_timeout
        return 'late'

    async def main():
        team = Team('to', client_factory=lambda inst: MockClient(handler=respond),
                    model_timeout=0.2)
        # 第一轮：query 比模型调用先超时（0.05 < 0.2）→ 返回空串而非旧文
        out1 = await team.query('first', timeout=0.05)
        await team.lead.wait_idle(2.0)
        # 第二轮：模型超时(0.2s)发生在 query 窗口(60s)内 → 错误文本可见
        out2 = await team.query('second')
        warns = [ev for ev in events if ev.kind == AGENT_WARN
                 and 'timed out' in str(ev.data.get('text', ''))]
        return out1, out2, len(warns)

    try:
        out1, out2, warn_count = asyncio.run(main())
    finally:
        clear_runtime_sinks()
    assert out1 == ''                                   # 不捞旧文
    assert 'timed out after 0.2s' in out2               # 本轮超时错误可见
    assert warn_count >= 1                              # AGENT_WARN 已 emit


def test_create_agent_tool_name_spawns_persistent_teammate():
    """对齐 claude：create_agent 带 name = 持久 teammate（登记进 team、
    mailbox 存活、可 send_message/task_stop）；不带 name = 一次性。"""
    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        return [ToolUse('create_agent',
                        {'prompt': 'do work', 'name': 'worker'}, 't1')]

    async def main():
        team = Team('m2', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        out = await team.execute_tool(
            'create_agent', {'prompt': 'do work', 'name': 'worker'}, lead)
        teammate_id = team.agent_id('worker')
        teammate = team.agents.get(teammate_id)
        try:
            persistent = (teammate is not None
                          and teammate_id in team.children.get(lead.agent_id, set())
                          and 'send_message' in out)
            # 一次性路径：不带 name，返回最终答案，不留持久 agent
            one_shot = await team.execute_tool(
                'create_agent', {'prompt': 'quick'}, lead)
            # claude：单 agent 模式下 name 被静默降级为一次性，不报错
            team_single = Team(
                'm3', client_factory=lambda inst: MockClient(handler=respond),
                multi_agent=False)
            single_out = await team_single.execute_tool(
                'create_agent', {'prompt': 'quick', 'name': 'w'}, team_single.lead)
            return persistent, one_shot, single_out
        finally:
            if teammate is not None:
                await team.stop_agent(teammate)

    persistent, one_shot, single_out = asyncio.run(main())
    assert persistent is True
    assert one_shot == 'done'
    assert single_out == 'done'   # name 静默忽略，仍是一次性
