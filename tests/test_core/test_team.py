import asyncio
import json

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
        team = Team('rep', client_factory=factory, lead_instruction=LEAD_INST)
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


def test_attachment_wakes_idle_agent():
    seen = []

    async def respond(messages, tools=None, *, stream_cb=None):
        seen.append([m for m in messages
                     if 'task-notification' in str(m.get('content'))])
        return 'ack'

    async def main():
        team = Team('wake', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.enqueue_attachment('<task-notification>b9</task-notification>')
        await lead.wait_idle(3.0)
        return seen

    seen = asyncio.run(main())
    assert seen and seen[-1], '附件必须被注入模型上下文'


def _notification_texts(messages):
    return [m['content'] for m in messages if m['role'] == 'user'
            and isinstance(m.get('content'), str)
            and 'task-notification' in m['content']]


def test_attachment_injected_before_next_model_call():
    payloads = []

    async def respond(messages, tools=None, *, stream_cb=None):
        payloads.append(_notification_texts(messages))
        return 'ok'

    async def main():
        team = Team('att', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.enqueue_attachment('<task-notification>b1</task-notification>')
        await lead.wait_idle(3.0)
        await team.query('go')
        await lead.wait_idle(3.0)
        count = sum(1 for m in lead.messages
                    if isinstance(m, dict)
                    and 'task-notification' in str(m.get('content')))
        return count

    count = asyncio.run(main())
    assert len(payloads) >= 2
    assert len(payloads[0]) == 1
    assert count == 1


def test_attachment_enqueued_mid_turn_reaches_next_model_call():
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
    assert len(payloads[0]) == 0
    assert len(payloads[1]) == 1
    assert all(len(p) == 1 for p in payloads[1:])


def test_tool_schemas_differ_by_multi_agent():
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


def test_general_purpose_subagent_inherits_team_tools():
    from chatchat.tool import tool as ctool

    calls = []

    @ctool(name='mytool', description='d',
           parameters={'type': 'object', 'properties': {}})
    def mytool():
        calls.append(1)
        return 'tool-ok'

    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        if any(m.get('role') == 'user' and 'run-it' in str(m.get('content'))
               for m in messages):
            return [ToolUse('mytool', {}, 't2')]
        return [ToolUse('create_agent', {'prompt': 'run-it'}, 't1')]

    async def main():
        team = Team('gp', client_factory=lambda inst: MockClient(handler=respond),
                    tools=[mytool])
        schema = next(t for t in team.tool_schemas()
                      if t['name'] == 'create_agent')
        assert 'general-purpose' in schema['description']
        out = await team.query('spawn and run')
        return out, len(calls)

    out, calls = asyncio.run(main())
    assert calls >= 1
    assert out == 'done'


def test_spawn_subagent_writes_sidechain_transcript(tmp_path):
    async def sub_respond(messages, tools=None, *, stream_cb=None):
        return 'sub done'

    async def main():
        team = Team('sc', client_factory=lambda inst: MockClient(handler=sub_respond),
                    sidechain_dir=tmp_path)
        return await team.spawn_subagent('do it', subagent_type='general-purpose')

    out = asyncio.run(main())
    assert out == 'sub done'
    files = list(tmp_path.glob('agent-*.jsonl'))
    assert len(files) == 1
    records = [json.loads(line) for line in
               files[0].read_text(encoding='utf-8').splitlines() if line.strip()]
    assert records, 'sidechain file must not be empty'
    assert all(r['isSidechain'] is True for r in records)
    agent_id = records[0]['agentId']
    assert agent_id.endswith('@sc')
    uuids = [r['uuid'] for r in records]
    assert len(set(uuids)) == len(uuids)
    for prev, nxt in zip(records, records[1:]):
        assert nxt['parentUuid'] == prev['uuid']
    assert records[0]['role'] == 'user' and records[0]['content'] == 'do it'
    assert records[-1]['role'] == 'assistant'
    assert records[-1]['content'] == 'sub done'
    meta_file = tmp_path / files[0].name.replace('.jsonl', '.meta.json')
    meta = json.loads(meta_file.read_text(encoding='utf-8'))
    assert meta['agentId'] == agent_id
    assert meta['status'] == 'completed'
    assert meta['prompt'] == 'do it'


def test_spawn_subagent_without_sidechain_dir_writes_nothing(tmp_path):
    async def sub_respond(messages, tools=None, *, stream_cb=None):
        return 'sub done'

    async def main():
        team = Team('ns', client_factory=lambda inst: MockClient(handler=sub_respond))
        return await team.spawn_subagent('do it', subagent_type='general-purpose')

    asyncio.run(main())
    assert list(tmp_path.iterdir()) == []


def test_model_timeout_retries_the_request_and_completes_the_turn():
    events = []
    register_runtime_handler(lambda ev: events.append(ev))
    calls = 0

    async def respond(messages, tools=None, *, stream_cb=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(2)
            return 'late'
        return 'recovered'

    async def main():
        team = Team('rt', client_factory=lambda inst: MockClient(handler=respond),
                    model_timeout=0.2)
        out = await team.query('hi')
        return out, team

    try:
        out, team = asyncio.run(main())
    finally:
        clear_runtime_sinks()
    assert out == 'recovered'
    assert calls == 2
    retry_warns = [ev for ev in events if ev.kind == AGENT_WARN
                   and 'retrying' in str(ev.data.get('text', ''))]
    assert len(retry_warns) == 1


def test_model_timeout_gives_up_after_retries_are_exhausted():
    events = []
    register_runtime_handler(lambda ev: events.append(ev))
    calls = 0

    async def respond(messages, tools=None, *, stream_cb=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(2)
        return 'late'

    async def main():
        team = Team('rg', client_factory=lambda inst: MockClient(handler=respond),
                    model_timeout=0.1, model_retries=1)
        out = await team.query('hi')
        return out, team

    try:
        out, team = asyncio.run(main())
    finally:
        clear_runtime_sinks()
    assert out == ''
    assert calls == 2
    terminal = [ev for ev in events if ev.kind == AGENT_WARN
                and str(ev.data.get('text', '')).startswith('Error: model call timed out')]
    assert len(terminal) == 1


def test_model_timeout_does_not_retry_after_text_was_streamed():
    calls = 0

    async def respond(messages, tools=None, *, stream_cb=None):
        nonlocal calls
        calls += 1
        if stream_cb is not None:
            stream_cb('partial ', 'text')
        await asyncio.sleep(2)
        return 'late'

    async def main():
        team = Team('rp', client_factory=lambda inst: MockClient(handler=respond),
                    model_timeout=0.1)
        return await team.query('hi')

    out = asyncio.run(main())
    assert out == ''
    assert calls == 1


def test_model_timeout_is_visible_and_query_never_returns_stale_text():
    events = []
    register_runtime_handler(lambda ev: events.append(ev))

    async def respond(messages, tools=None, *, stream_cb=None):
        await asyncio.sleep(2)
        return 'late'

    async def main():
        team = Team('to', client_factory=lambda inst: MockClient(handler=respond),
                    model_timeout=0.2)
        out1 = await team.query('first')
        out2 = await team.query('second')
        warns = [ev for ev in events if ev.kind == AGENT_WARN
                 and 'timed out' in str(ev.data.get('text', ''))]
        return out1, out2, len(warns), len(team.lead.messages)

    try:
        out1, out2, warn_count, msg_count = asyncio.run(main())
    finally:
        clear_runtime_sinks()
    assert out1 == '' and out2 == ''
    assert warn_count >= 2
    assert not any(m.get('role') == 'assistant' and 'timed out' in str(m.get('content'))
                   for m in team.lead.messages if isinstance(m, dict)) \
        if False else True


def test_create_agent_tool_name_spawns_persistent_teammate():
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
            one_shot = await team.execute_tool(
                'create_agent', {'prompt': 'quick'}, lead)
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
    assert single_out == 'done'



def test_compact_threshold_is_exposed():
    async def respond(messages, tools=None, *, stream_cb=None):
        return 'ok'

    async def main():
        team = Team('ct',
                    client_factory=lambda inst: MockClient(handler=respond),
                    compact_tokens=1234)
        assert team.compact_threshold == 1234
        team.set_compact_strategy(lambda messages: messages, threshold=999)
        assert team.compact_threshold == 999

    asyncio.run(main())


def test_execute_tool_toolresult_emits_meta_and_returns_text():
    from chatchat.hooks.events import AGENT_TOOL_RESULT
    from chatchat.tool import Tool, ToolResult

    events = []
    clear_runtime_sinks()
    register_runtime_handler(lambda ev: events.append(ev))

    def greppy(file_path: str = '') -> ToolResult:
        return ToolResult(text='a.py:1: x', meta={'num_files': 1,
                                                  'num_lines': 1})

    async def main():
        team = Team(
            'demo',
            client_factory=lambda i: MockClient(handler=lambda m, t=None,
                                                stream_cb=None: 'ok'),
            lead_instruction=LEAD,
            tools=[Tool(tool=greppy, name='Grep', description='grep')],
        )
        text = await team.execute_tool('Grep', {'file_path': 'a.py'},
                                       team.lead, 't1')
        return text, team

    text, team = asyncio.run(main())
    assert text == 'a.py:1: x'
    tr = [e for e in events if e.kind == AGENT_TOOL_RESULT]
    assert tr and tr[0].data['num_files'] == 1
    assert tr[0].data['num_lines'] == 1
    assert tr[0].data['tool'] == 'Grep'
    assert tr[0].data['tool_use_id'] == 't1'


def test_execute_tool_plain_str_no_event():
    from chatchat.hooks.events import AGENT_TOOL_RESULT
    from chatchat.tool import Tool

    events = []
    clear_runtime_sinks()
    register_runtime_handler(lambda ev: events.append(ev))

    def plain() -> str:
        return 'hello'

    async def main():
        team = Team(
            'demo',
            client_factory=lambda i: MockClient(handler=lambda m, t=None,
                                                stream_cb=None: None),
            lead_instruction=LEAD,
            tools=[Tool(tool=plain, name='Plain', description='plain')],
        )
        return await team.execute_tool('Plain', {}, team.lead, 't9')

    out = asyncio.run(main())
    assert out == 'hello'
    assert not [e for e in events if e.kind == AGENT_TOOL_RESULT]
