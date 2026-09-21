import asyncio
import inspect
import json

from chatchat.client import MockClient, ToolUse
from chatchat.core import team as core_team
from chatchat.core.agents import AgentDefinition
from chatchat.core.inbox_poller import InboxPoller
from chatchat.core.mailbox import Mailbox
from chatchat.hooks.events import (AGENT_PROGRESS, AGENT_STATE, AGENT_TOOL_CALL,
                                   AGENT_TOOL_RESULT, AGENT_WARN,
                                   register_runtime_handler)
from chatchat.team import Team
from chatchat.tool import Tool, ToolResult, tool as ctool
from helpers import mock_team

LEAD = ('你是 team lead。把任务拆开用 send_message 发给 teammate 并等回信，'
        '最后汇总最终答案。')
RESEARCHER = '你是 researcher。收到任务后用 send_message 回研究结论，然后结束。'


def _multi_team(name, handler=None):
    return mock_team(name, handler, lead_instruction=LEAD, multi_agent=True)


def _events():
    collected = []
    register_runtime_handler(collected.append)
    return collected


def _warns(events, phrase):
    return [ev for ev in events if ev.kind == AGENT_WARN
            and phrase in str(ev.data.get('text', ''))]


def _notification_texts(messages):
    return [m['content'] for m in messages if m['role'] == 'user'
            and isinstance(m.get('content'), str)
            and 'task-notification' in m['content']]


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

    def factory(instruction, model=None):
        if 'researcher' in instruction:
            return MockClient(handler=researcher_respond)
        return MockClient(handler=lead_respond)

    return Team('demo', client_factory=factory, lead_instruction=LEAD)


def test_team_send_message_flow_and_tool_event():
    events = _events()

    async def main():
        team = make_team()
        team.create_agent('researcher', instruction=RESEARCHER)
        return await team.query('调研一下 DeepSeek', timeout=15)

    answer = asyncio.run(main())
    assert '汇总' in answer
    assert any(ev.kind == AGENT_TOOL_CALL for ev in events)


def test_wait_idle_not_satisfied_by_stale_idle_set():
    async def respond(messages, tools=None, *, stream_cb=None):
        await asyncio.sleep(0.3)
        return 'ok'

    async def main():
        lead = mock_team('race', respond).lead
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


def test_interrupt_and_submit_aborts_only_a_cancelable_running_tool():
    for tool, aborted in (('sleep_long', True), ('bash', False)):
        async def respond(messages, tools=None, *, stream_cb=None):
            if any(isinstance(m.get('content'), list) for m in messages):
                return 'done'
            return [ToolUse(tool, {}, 'x1')]

        async def main():
            lead = mock_team('int', respond).lead
            lead.submit('start')
            lead._in_tool = tool
            lead.interrupt_and_submit('new msg', cancelable_tools=('sleep_long',))
            interrupted = lead._work_abort.aborted
            try:
                await asyncio.wait_for(lead.wait_idle(), 1.5)
            except asyncio.TimeoutError:
                pass
            return interrupted

        assert asyncio.run(main()) is aborted


def test_report_surfaces_when_lead_never_writes_text():
    LEAD_INST = 'LEAD_PROMPT'
    report = '# DeepSeek 综合研究报告\nDeepSeek 是深度求索。'

    async def lead_respond(messages, tools=None, *, stream_cb=None):
        return [ToolUse('create_agent', {'prompt': '再细化'}, 'd1')]

    async def sub_respond(messages, tools=None, *, stream_cb=None):
        return report

    def factory(instruction, model=None):
        return MockClient(handler=lead_respond if instruction == LEAD_INST
                          else sub_respond)

    async def main():
        team = Team('rep', client_factory=factory, lead_instruction=LEAD_INST)
        return await team.query('给我一份 deepseek 报告', timeout=15)

    ans = asyncio.run(main())
    assert 'DeepSeek 综合' in ans
    assert not ans.startswith('Error')


def test_inbox_frame_is_counted_as_pending():
    async def main():
        release = asyncio.Event()

        async def respond(messages, tools=None, *, stream_cb=None):
            await release.wait()
            return 'ok'

        lead = mock_team('inbox', respond).lead
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
        seen.append(_notification_texts(messages))
        return 'ack'

    async def main():
        lead = mock_team('wake', respond).lead
        lead.enqueue_attachment('<task-notification>b9</task-notification>')
        await lead.wait_idle(3.0)

    asyncio.run(main())
    assert seen and seen[-1], '附件必须被注入模型上下文'


def test_attachment_injected_before_next_model_call():
    payloads = []

    async def respond(messages, tools=None, *, stream_cb=None):
        payloads.append(_notification_texts(messages))
        return 'ok'

    async def main():
        team = mock_team('att', respond)
        lead = team.lead
        lead.enqueue_attachment('<task-notification>b1</task-notification>')
        await lead.wait_idle(3.0)
        await team.query('go')
        await lead.wait_idle(3.0)
        return len(_notification_texts(lead.messages))

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
        team = mock_team('att2', respond)
        holder['lead'] = team.lead
        return await team.query('go')

    asyncio.run(main())
    assert len(payloads) >= 2
    assert len(payloads[0]) == 0
    assert len(payloads[1]) == 1
    assert all(len(p) == 1 for p in payloads[1:])


def test_tool_schemas_differ_by_multi_agent():
    async def ok(messages, tools=None, *, stream_cb=None):
        return 'ok'

    async def names(**kw):
        team = mock_team('m', ok, **kw)
        return {t['name'] for t in team.tool_schemas(team.tool_context)}

    single = asyncio.run(names(multi_agent=False))
    multi = asyncio.run(names())
    assert 'create_agent' in single and 'create_agent' in multi
    assert 'send_message' not in single and 'task_stop' not in single
    assert {'send_message', 'task_stop'} <= multi


def test_general_purpose_subagent_inherits_team_tools():
    calls = []

    @ctool(name='mytool', description='d',
           parameters={'type': 'object', 'properties': {}})
    def mytool(context):
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
        team = mock_team('gp', respond, tools=[mytool])
        schema = next(t for t in team.tool_schemas(team.tool_context)
                      if t['name'] == 'create_agent')
        assert 'general-purpose' in schema['description']
        return await team.query('spawn and run')

    out = asyncio.run(main())
    assert calls
    assert out == 'done'


def test_subagent_model_resolution_param_over_def_over_inherit():
    seen = []

    def factory(instruction, model=None):
        seen.append(model)
        return MockClient(handler=lambda messages, tools=None: 'ok')

    async def main():
        team = Team('mr', client_factory=factory)
        team.register_agent_definition(AgentDefinition(
            'reader', system_prompt='read stuff', model='def-model'))
        await team.spawn_subagent('go', subagent_type='reader')
        await team.spawn_subagent('go', subagent_type='reader',
                                  model='param-model')
        await team.spawn_subagent('go')
        return seen

    assert asyncio.run(main()) == [None, 'def-model', 'param-model', None]


def test_create_agent_tool_passes_model_and_schema_exposes_it():
    seen = []

    def factory(instruction, model=None):
        seen.append(model)
        return MockClient(handler=lambda messages, tools=None: 'ok')

    async def main():
        team = Team('cm', client_factory=factory)
        out = await team.execute_tool('create_agent',
                                      {'prompt': 'x', 'model': 'm2'},
                                      team.lead, 't1')
        schema = team.tool_schemas(team.tool_context)[0]['input_schema']['properties']
        return out, schema

    out, schema = asyncio.run(main())
    assert 'ok' in out.text
    assert seen == [None, 'm2']
    assert 'model' in schema


def test_spawned_subagent_carries_definition_agent_type():
    async def main():
        team = mock_team('at', lambda messages, tools=None: 'ok')
        team.register_agent_definition(AgentDefinition(
            'reader', system_prompt='read stuff'))
        await team.spawn_subagent('go', subagent_type='reader')
        return [a.agent_type for a in team.agents.values() if a._internal]

    assert asyncio.run(main()) == ['reader']


def test_spawn_subagent_writes_sidechain_transcript(tmp_path):
    async def sub_respond(messages, tools=None, *, stream_cb=None):
        return 'sub done'

    async def main():
        team = mock_team('sc', sub_respond, sidechain_dir=tmp_path)
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


def test_model_timeout_retries_the_request_and_completes_the_turn():
    events = _events()
    calls = 0

    async def respond(messages, tools=None, *, stream_cb=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(2)
            return 'late'
        return 'recovered'

    async def main():
        team = mock_team('rt', respond, model_timeout=0.2)
        return await team.query('hi')

    out = asyncio.run(main())
    assert out == 'recovered'
    assert calls == 2
    assert len(_warns(events, 'retrying')) == 1


def test_model_timeout_gives_up_without_stale_text_in_the_transcript():
    events = _events()
    calls = 0

    async def respond(messages, tools=None, *, stream_cb=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(2)
        return 'late'

    async def main():
        team = mock_team('rg', respond, model_timeout=0.1, model_retries=1)
        return await team.query('hi'), team.lead.messages

    out, messages = asyncio.run(main())
    assert out == ''
    assert calls == 2
    assert len(_warns(events, 'Error: model call timed out')) == 1
    assert not [m for m in messages if isinstance(m, dict)
                and m.get('role') == 'assistant'
                and 'timed out' in str(m.get('content'))]


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
        team = mock_team('rp', respond, model_timeout=0.1)
        return await team.query('hi')

    out = asyncio.run(main())
    assert out == ''
    assert calls == 1


def test_create_agent_tool_name_spawns_persistent_teammate():
    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'done'
        return [ToolUse('create_agent',
                        {'prompt': 'do work', 'name': 'worker'}, 't1')]

    async def main():
        team = mock_team('m2', respond)
        lead = team.lead
        out = await team.execute_tool(
            'create_agent', {'prompt': 'do work', 'name': 'worker'}, lead)
        teammate_id = team.agent_id('worker')
        teammate = team.agents.get(teammate_id)
        try:
            persistent = (teammate is not None
                          and teammate_id in team.children.get(lead.agent_id, set())
                          and 'send_message' in out.text)
            one_shot = await team.execute_tool(
                'create_agent', {'prompt': 'quick'}, lead)
            team_single = mock_team('m3', respond, multi_agent=False)
            single_out = await team_single.execute_tool(
                'create_agent', {'prompt': 'quick', 'name': 'w'}, team_single.lead)
            return persistent, one_shot, single_out
        finally:
            if teammate is not None:
                await team.stop_agent(teammate)

    persistent, one_shot, single_out = asyncio.run(main())
    assert persistent is True
    assert one_shot.text == 'done'
    assert single_out.text == 'done'


def test_the_context_budget_is_a_threshold_over_the_measured_occupancy():
    async def main():
        threshold = mock_team('ct', context_window=1_634,
                          compact_reserve=400).compact_threshold
        return threshold, mock_team('co', context_window=1_000)

    threshold, team = asyncio.run(main())
    assert threshold == 1234

    assert team.auto_compact is True
    assert team.context_tokens == 0
    team.lead.messages.append({'role': 'user', 'content': 'x' * 400})
    assert team.context_tokens == 0
    team.lead.messages.append(
        {'role': 'assistant', 'content': 'a',
         'usage': {'prompt_tokens': 90, 'completion_tokens': 10}})
    team.lead.messages.append({'role': 'user', 'content': 'y' * 40})
    assert team.context_tokens == 100


def test_execute_tool_forwards_a_toolresult_meta_into_the_result_event():
    events = _events()

    def greppy(context, file_path: str = '') -> ToolResult:
        return ToolResult(text='a.py:1: x', meta={'num_files': 1,
                                                  'num_lines': 1})

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: 'ok',
                     lead_instruction=LEAD,
                     tools=[Tool(tool=greppy, name='Grep', description='grep')])
        return await team.execute_tool('Grep', {'file_path': 'a.py'},
                                       team.lead, 't1')

    outcome = asyncio.run(main())
    assert outcome.text == 'a.py:1: x'
    tr = [e for e in events if e.kind == AGENT_TOOL_RESULT]
    assert tr and tr[0].data['num_files'] == 1
    assert tr[0].data['num_lines'] == 1
    assert tr[0].data['tool'] == 'Grep'
    assert tr[0].data['tool_use_id'] == 't1'


def test_execute_tool_of_a_plain_str_result_emits_no_meta_event():
    events = _events()

    def plain(context) -> str:
        return 'hello'

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: None,
                     lead_instruction=LEAD,
                     tools=[Tool(tool=plain, name='Plain', description='plain')])
        return await team.execute_tool('Plain', {}, team.lead, 't9')

    out = asyncio.run(main())
    assert out.text == 'hello'
    assert not [e for e in events if e.kind == AGENT_TOOL_RESULT]


def test_create_agent_carries_tool_use_id_on_progress():
    events = _events()

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: 'sub answer',
                     lead_instruction=LEAD)
        return await team.execute_tool('create_agent', {'prompt': 'go'},
                                       team.lead, 'tu-1')

    out = asyncio.run(main())
    assert out.text == 'sub answer'
    started = [e for e in events
               if e.kind == AGENT_PROGRESS and e.data.get('tool_use_id')]
    assert started, 'the spawn must carry the spawning tool_use_id'
    assert started[0].data['tool_use_id'] == 'tu-1'
    assert started[0].data['prompt'] == 'go'
    assert isinstance(started[0].data['started_at'], float)


def test_agent_state_reports_busy_when_a_teammate_starts_a_turn():
    events = _events()

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: 'done',
                     lead_instruction=LEAD)
        worker = team.create_agent('worker', instruction='w', depth=1)
        worker.submit('start')
        await worker.wait_idle()
        await asyncio.sleep(0.05)

    asyncio.run(main())
    busy = [ev.data.get('busy') for ev in events if ev.kind == AGENT_STATE]
    assert True in busy, 'busy must be observable while the turn runs'
    assert busy[-1] is False


def test_every_dispatched_tool_accepts_the_spawning_tool_use_id():
    """execute_tool hands `tool_use_id` to every built-in tool positionally."""
    for name in ('send_message', 'create_agent', 'task_stop'):
        signature = inspect.signature(getattr(core_team._tools, name))
        params = list(signature.parameters)
        assert params[-1] == 'tool_use_id', f'{name} dropped tool_use_id'
        assert signature.parameters['tool_use_id'].default == ''


def test_task_stop_stops_a_teammate_created_through_create_agent():
    async def idle(messages, tools=None, *, stream_cb=None):
        return 'idle'

    async def main():
        team = _multi_team('demo', idle)
        spawned = await team.execute_tool('create_agent',
                                          {'prompt': 'watch the build',
                                           'name': 'watcher'},
                                          team.lead, 'tu-1')
        assert 'spawned and idle' in spawned.text
        watcher = team.get_by_name('watcher')
        assert watcher is not None
        assert team.children[team.lead.agent_id] == {watcher.agent_id}

        out = await team.execute_tool('task_stop', {'name': 'watcher'},
                                      team.lead, 'tu-2')
        return team, watcher, out

    team, watcher, out = asyncio.run(main())
    assert 'is not your sub-agent' not in out.text
    assert out.text == f'agent {watcher.agent_id} stopped'
    assert team.children[team.lead.agent_id] == set()
    assert watcher.agent_id not in team.parents


def test_task_stop_refuses_an_agent_that_is_not_your_child():
    async def idle(messages, tools=None, *, stream_cb=None):
        return 'idle'

    async def main():
        team = _multi_team('demo', idle)
        team.create_agent('stray', instruction='x', depth=1)
        return await team.execute_tool('task_stop', {'name': 'stray'},
                                       team.lead, 'tu-3')

    assert asyncio.run(main()).text == 'Error: "stray" is not your sub-agent'


def test_spawned_agent_tool_calls_run_the_pre_tool_gate():
    ran = []

    @ctool(name='mytool', description='d', parameters={})
    def mytool(context):
        ran.append(1)
        return 'ran'

    async def responder(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'finished'
        return [ToolUse('mytool', {}, 'g1')]

    async def main():
        team = mock_team('gate', responder, tools=[mytool])
        team.hooks.register('PreToolUse', fn=lambda h: False,
                            error_message='not allowed')
        await team.spawn_subagent('use mytool')
        return team

    team = asyncio.run(main())
    assert ran == []
    sub = next(a for a in team.agents.values() if a is not team.lead)
    assert 'not allowed' in str(sub.messages[-2])


def test_spawned_agent_is_restricted_to_its_own_tools():
    ran = []

    @ctool(name='mine', description='d', parameters={})
    def mine(context):
        ran.append('mine')
        return 'mine ran'

    @ctool(name='theirs', description='d', parameters={})
    def theirs(context):
        ran.append('theirs')
        return 'theirs ran'

    seen = []

    async def responder(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'finished'
        seen.append(sorted(t['name'] for t in tools or []))
        return [ToolUse('theirs', {}, 'g2')]

    async def main():
        team = mock_team('subset', responder, tools=[mine, theirs])
        team.define_agent('worker', system_prompt='w', tools=[mine])
        await team.spawn_subagent('go', subagent_type='worker')
        return team

    team = asyncio.run(main())
    sub = next(a for a in team.agents.values() if a is not team.lead)
    assert seen == [['mine']]
    assert ran == []
    assert 'not available' in str(sub.messages[-2])
