import asyncio
import time

import pytest

from chatchat.client import MockClient, ToolUse
from chatchat.core.agents import AgentDefinition
from chatchat.core.tools import send_message
from chatchat.hooks.events import AGENT_WARN, register_runtime_handler
from chatchat.team import LEAD_NAME, Team
from chatchat.tool import Tool


@pytest.fixture
def team():
    def make(handler=None, hooks=True):
        return Team('demo', MockClient(handler=handler), hooks=hooks)

    return make


def _output(event, **fields):
    return {'hookSpecificOutput': {'hookEventName': event, **fields}}


def _watch(seen, pick=None):
    def hook(inp):
        seen.append(pick(inp) if pick else inp)
        return True

    return hook


async def _run_pre_tool_hook(team, reply, tool_input=None):
    t = team()
    t.hooks.on('PreToolUse', fn=lambda inp: reply)
    return await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash',
                                                tool_input or {})


async def _run_command_hook(team, command):
    t = team()
    t.hooks.register('PreToolUse', 'Bash', command=command)
    return await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})


async def _prompt_hook(team, reply):
    t = team(handler=lambda messages, tools=None, *, stream_cb=None: reply)
    t.hooks.register('PreToolUse', 'Bash', prompt='is this command safe?')
    return await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})


def _stops_after_one_tool_call(messages, tools=None, *, stream_cb=None):
    if any(isinstance(m.get('content'), list) for m in messages):
        return 'stop'
    return [ToolUse('SendMessage', {'to': 'nobody'}, 't1')]


def _tool_result_blocks(messages):
    return [m['content'] for m in messages
            if isinstance(m.get('content'), list)
            and any(b.get('type') == 'tool_result' for b in m['content'])]


def _record_prompts(seen, reply='ok'):
    def handler(messages, tools=None, *, stream_cb=None):
        seen.append([m.get('content') for m in messages])
        return reply

    return handler


def test_function_hook_allow(team):
    seen = []

    async def main():
        t = team()
        t.hooks.on('PreToolUse', fn=_watch(seen, lambda inp: inp['tool_name']))
        await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})

    asyncio.run(main())
    assert seen == ['Bash']


def test_function_hook_block(team):
    agg = asyncio.run(_run_pre_tool_hook(team, False))
    assert agg.blocking_error is not None
    assert not agg.success


def test_function_hook_json_updated_input(team):
    agg = asyncio.run(_run_pre_tool_hook(
        team,
        _output('PreToolUse', permissionDecision='allow',
                updatedInput={'command': 'git x'}),
        {'command': 'git y'}))
    assert agg.success
    assert agg.updated_input == {'command': 'git x'}


def test_command_hook_exit_two_blocks(team):
    agg = asyncio.run(_run_command_hook(team, 'echo nope; exit 2'))
    assert agg.blocking_error is not None
    assert 'nope' in agg.blocking_error.blocking_error


def test_command_hook_echo_success(team):
    agg = asyncio.run(_run_command_hook(team, 'echo hello'))
    assert agg.success
    assert any('hello' in r.stdout for r in agg.results)


def test_prompt_hook_answers_from_the_model(team):
    agg = asyncio.run(_prompt_hook(team, '{"ok": true}'))
    assert agg.success
    assert agg.results[0].outcome == 'success'


def test_prompt_hook_reason_blocks(team):
    agg = asyncio.run(_prompt_hook(
        team, '{"ok": false, "reason": "writes outside the project"}'))
    assert agg.blocking_error is not None
    assert 'writes outside the project' in agg.blocking_error.blocking_error


def test_a_model_reply_that_is_not_a_condition_fails_the_hook(team):
    agg = asyncio.run(_prompt_hook(team, 'that looks fine to me'))
    assert agg.results[0].outcome == 'non_blocking_error'
    assert 'that looks fine to me' in agg.results[0].message


def test_matched_hooks_run_in_parallel(team):
    async def main():
        t = team()

        def slow(_):
            time.sleep(0.3)
            return True

        t.hooks.register('Stop', fn=slow)
        t.hooks.register('Stop', fn=slow)
        start = time.monotonic()
        await t.hooks.execute_stop_hooks(t.lead)
        assert time.monotonic() - start < 0.55

    asyncio.run(main())


def test_per_hook_timeout(team):
    async def main():
        t = team()

        async def slow(_):
            await asyncio.sleep(1)
            return True

        t.hooks.register('Stop', fn=slow, timeout=0.05)
        agg = await t.hooks.execute_stop_hooks(t.lead)
        assert any(r.outcome == 'non_blocking_error' and 'timed out' in r.message
                   for r in agg.results)

    asyncio.run(main())


def test_a_timed_out_command_hook_is_killed(team, tmp_path):
    marker = tmp_path / 'late'

    async def main():
        t = team()
        t.hooks.register('Stop', command=f'sleep 0.4; touch {marker}',
                         timeout=0.05)
        return await t.hooks.execute_stop_hooks(t.lead)

    agg = asyncio.run(main())
    assert agg.results[0].outcome == 'non_blocking_error'
    time.sleep(0.6)
    assert not marker.exists()


def test_matcher_filters(team):
    async def main():
        t = team()
        t.hooks.register('PreToolUse', 'Bash', fn=lambda inp: True)
        t.hooks.register('PreToolUse', 'Read', fn=lambda inp: True)
        agg = await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        assert len(agg.results) == 1

    asyncio.run(main())


def test_session_hook_remove(team):
    async def main():
        t = team()
        hid = t.hooks.register('Stop', fn=lambda inp: True)
        t.hooks.remove_hook(hid)
        agg = await t.hooks.execute_stop_hooks(t.lead)
        assert agg.results == []

    asyncio.run(main())


def test_once_runs_single_time(team):
    async def main():
        t = team()
        count = {'n': 0}

        def inc(_):
            count['n'] += 1
            return True

        t.hooks.register('Stop', fn=inc, once=True)
        await t.hooks.execute_stop_hooks(t.lead)
        await t.hooks.execute_stop_hooks(t.lead)
        assert count['n'] == 1

    asyncio.run(main())


def test_user_prompt_submit_block_drops_the_prompt(team):
    async def main():
        t = team()
        t.hooks.on('UserPromptSubmit', fn=lambda inp: False)
        answer = await t.query('go')
        return t, answer

    t, answer = asyncio.run(main())
    assert answer == ''
    assert all(m.get('role') != 'assistant' for m in t.lead.messages)
    assert all(m.get('content') != 'go' for m in t.lead.messages
               if isinstance(m.get('content'), str))


def test_user_prompt_submit_additional_context_reaches_the_model(team):
    seen = []

    async def main():
        t = team(handler=_record_prompts(seen))
        t.hooks.on('UserPromptSubmit',
                   fn=lambda inp: _output('UserPromptSubmit',
                                          additionalContext='extra context'))
        return await t.query('go')

    asyncio.run(main())
    assert any('extra context' in str(entry) for entry in seen[0])


def test_setup_and_session_start_context_opens_the_lead_transcript(team):
    seen = []

    async def main():
        t = team(handler=_record_prompts(seen))
        t.hooks.on('Setup', fn=lambda inp: _output(
            'Setup', additionalContext='index rebuilt'))
        t.hooks.on('SessionStart', fn=lambda inp: _output(
            'SessionStart', additionalContext='branch: main'))
        await t.query('go')
        return t.lead.messages

    messages = asyncio.run(main())
    assert [m.get('content') for m in messages[:3]] == \
        ['index rebuilt', 'branch: main', 'go']
    assert seen[0][:2] == ['index rebuilt', 'branch: main']


def test_setup_and_session_start_hooks_fire_once_per_team(team):
    calls = []

    async def main():
        t = team()
        t.hooks.on('Setup', fn=lambda inp: calls.append('setup') or True)
        t.hooks.on('SessionStart', fn=lambda inp: calls.append('start') or True)
        await t.query('first')
        await t.query('second')
        return calls

    assert asyncio.run(main()) == ['setup', 'start']


def test_subagent_start_context_opens_the_sub_agent_transcript(team):
    seen = []

    async def main():
        t = team(handler=_record_prompts(seen, 'done'))
        t.hooks.on('SubagentStart', fn=lambda inp: _output(
            'SubagentStart', additionalContext='work from the repo'))
        return await t.spawn_subagent('do it')

    assert asyncio.run(main()) == 'done'
    assert seen[0] == ['work from the repo', 'do it']


def test_the_subagent_stop_hook_reports_the_type_and_the_final_answer(team):
    seen = []

    async def main():
        t = team(handler=lambda messages, tools=None, *, stream_cb=None:
                 'all clear')
        t.register_agent_definition(AgentDefinition('code-reviewer',
                                                    system_prompt='report issues'))
        t.hooks.on('SubagentStop', fn=_watch(seen))
        await t.spawn_subagent('do it')
        await t.spawn_subagent('do it', subagent_type='code-reviewer')
        return seen

    seen = asyncio.run(main())
    assert [s['agent_type'] for s in seen] == ['general-purpose',
                                               'code-reviewer']
    assert all(s['last_assistant_message'] == 'all clear' for s in seen)


def test_an_event_without_a_match_key_runs_every_hook(team):
    seen = []

    async def main():
        t = team()
        t.hooks.register('TaskCreated', 'Bash',
                         fn=_watch(seen))
        await t.hooks.execute_task_created_hooks(t.lead, 'task-1',
                                                 'refactor the parser')
        return seen

    seen = asyncio.run(main())
    assert seen[0]['task_id'] == 'task-1'
    assert seen[0]['task_subject'] == 'refactor the parser'
    assert seen[0]['teammate_name'] == LEAD_NAME
    assert seen[0]['team_name'] == 'demo'


def test_a_notification_hook_sees_the_message_text(tmp_path):
    seen = []

    async def main():
        t = Team('notify', MockClient(), mailbox_dir=tmp_path)
        t.create_agent('worker')
        t.hooks.on('Notification', fn=_watch(seen))
        await send_message(t, t.lead, {'to': 'worker', 'message': 'start now'})
        return seen

    seen = asyncio.run(main())
    assert seen[0]['notification_type'] == 'message'
    assert seen[0]['message'] == 'start now'
    assert seen[0]['title'] == f'{LEAD_NAME} -> worker'


def test_a_teammate_keeps_working_when_the_idle_hook_blocks(team):
    async def respond(messages, tools=None, *, stream_cb=None):
        texts = [c for c in (m.get('content') for m in messages)
                 if isinstance(c, str)]
        if any('finish the tests' in c for c in texts):
            return 'after feedback'
        if 'x' in texts or any(isinstance(m.get('content'), list)
                               for m in messages):
            return 'idle'
        return [ToolUse('Agent', {'prompt': 'x', 'name': 'worker'},
                        't1')]

    blocked = []

    def idle_hook(inp):
        blocked.append(1)
        return ({'decision': 'block', 'reason': 'finish the tests'}
                if len(blocked) == 1 else True)

    async def main():
        t = team(handler=respond)
        t.hooks.on('TeammateIdle', fn=idle_hook)
        await t.query('go')
        worker = t.get_by_name('worker')
        await worker.wait_idle(3.0)
        return worker.messages

    messages = asyncio.run(main())
    assert messages[-1]['role'] == 'assistant'
    assert messages[-1]['content'] == 'after feedback'


def test_a_blocked_task_created_hook_cancels_the_sub_agent(team):
    async def respond(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get('content'), list) for m in messages):
            return 'stop'
        return [ToolUse('Agent', {'prompt': 'do it'}, 't1')]

    async def main():
        t = team(handler=respond)
        t.hooks.register('TaskCreated', fn=lambda inp: False,
                         error_message='no sub-agents while the suite is red')
        await t.query('go')
        return [b for m in t.lead.messages if isinstance(m.get('content'), list)
                for b in m['content'] if b.get('type') == 'tool_result']

    results = asyncio.run(main())
    assert 'no sub-agents while the suite is red' in results[0]['content']


def test_post_tool_context_reaches_the_model_on_success_and_failure(team):
    async def ok(context, **kw):
        return 'worked'

    async def boom(context, **kw):
        raise RuntimeError('disk gone')

    async def main():
        t = Team('post', MockClient(),
                 tools=[Tool(tool=ok, name='Ok', description='ok'),
                        Tool(tool=boom, name='Boom', description='boom')])
        t.hooks.on('PostToolUse', fn=lambda inp: _output(
            'PostToolUse', additionalContext='tell the user'))
        t.hooks.on('PostToolUseFailure', fn=lambda inp: _output(
            'PostToolUseFailure', additionalContext='explain the failure'))
        return (await t.execute_tool('Ok', {}, t.lead, 't1'),
                await t.execute_tool('Boom', {}, t.lead, 't2'))

    good, bad = asyncio.run(main())
    assert (good.text, good.additional_context) == ('worked', 'tell the user')
    assert 'disk gone' in bad.text
    assert bad.additional_context == 'explain the failure'


def test_a_restored_transcript_starts_the_session_as_a_resume(team):
    seen = []

    async def main():
        t = team()
        t.hooks.on('SessionStart',
                   fn=_watch(seen, lambda inp: inp['source']))
        t.restore([{'role': 'user', 'content': 'earlier'}])
        await t.query('go')
        return seen

    assert asyncio.run(main()) == ['resume']


def test_instructions_loaded_hook_reports_the_file_and_its_scope(team):
    seen = []

    async def main():
        t = team()
        t.set_instruction_files([{'path': '/tmp/AGENTS.md',
                                  'content': 'project rules',
                                  'memory_type': 'Project',
                                  'load_reason': 'session_start'}])
        t.hooks.on('InstructionsLoaded',
                   fn=_watch(seen))
        await t.query('go')
        return seen

    seen = asyncio.run(main())
    assert seen and seen[0]['file_path'] == '/tmp/AGENTS.md'
    assert seen[0]['memory_type'] == 'Project'
    assert seen[0]['load_reason'] == 'session_start'


def test_instructions_loaded_hook_fires_once_per_session(team):
    calls = []

    async def main():
        t = team()
        t.set_instruction_files([{'path': 'p', 'content': 'c'}])
        t.hooks.on('InstructionsLoaded', fn=lambda inp: calls.append(1) or True)
        await t.query('first')
        await t.query('second')
        return calls

    assert len(asyncio.run(main())) == 1


def test_stop_hook_blocking_feedback_continues_turn(team):
    calls = []

    async def respond(messages, tools=None, *, stream_cb=None):
        texts = [c for c in (m.get('content') for m in messages)
                 if isinstance(c, str)]
        if any('keep going' in c for c in texts):
            return 'after feedback'
        calls.append(1)
        return 'initial'

    async def main():
        t = team(handler=respond)
        t.hooks.on('Stop', fn=lambda inp: (
            {'decision': 'block', 'reason': 'keep going'}
            if not inp.get('stop_hook_active') else True))
        return await t.query('go'), len(calls)

    ans, initial_calls = asyncio.run(main())
    assert ans == 'after feedback'
    assert initial_calls == 1


def test_pre_tool_block_reaches_agent_as_tool_result(team):
    async def main():
        t = team(handler=_stops_after_one_tool_call)
        t.hooks.on('PreToolUse', fn=lambda inp: False)
        await t.query('go')
        contents = [m.get('content') for m in t.lead.messages
                    if isinstance(m.get('content'), list)]
        assert any('hook blocked tool' in (r.get('content') or '')
                   for rs in contents for r in rs)

    asyncio.run(main())


def test_pre_tool_additional_context_sits_beside_the_tool_result(team):
    async def main():
        t = team(handler=_stops_after_one_tool_call)
        t.hooks.on('PreToolUse', fn=lambda inp: _output(
            'PreToolUse', permissionDecision='allow',
            additionalContext='run the tests first'))
        await t.query('go')
        return _tool_result_blocks(t.lead.messages)

    results = asyncio.run(main())
    assert len(results) == 1
    assert results[0][0]['type'] == 'tool_result'
    assert results[0][-1] == {'type': 'text', 'text': 'run the tests first'}


def test_a_tool_result_without_extra_context_stands_alone(team):
    async def main():
        t = team(handler=_stops_after_one_tool_call)
        await t.query('go')
        return _tool_result_blocks(t.lead.messages)

    assert len(asyncio.run(main())[0]) == 1


def test_execute_tool_reports_the_tool_text_and_the_hook_context(team):
    async def main():
        t = team()
        t.hooks.on('PreToolUse',
                   fn=lambda inp: _output('PreToolUse',
                                          permissionDecision='allow',
                                          additionalContext='extra'))
        return await t.execute_tool('unknown_tool', {}, t.lead, 't1')

    outcome = asyncio.run(main())
    assert outcome.text == ('Error: tool "unknown_tool" is not available '
                            'to this agent')
    assert outcome.additional_context == 'extra'


def test_hookless_agent_skips_emits(team):
    async def main():
        t = team()
        seen = []
        t.hooks.on('UserPromptSubmit', fn=_watch(seen, lambda _: 1))
        t.lead.hookless = True
        await t.query('go')
        assert seen == []

    asyncio.run(main())


def test_execute_tool_skips_hooks_only_for_hookless_agents(team):
    async def main():
        t = team()
        seen = []
        t.hooks.on('PreToolUse', fn=_watch(seen, lambda _: 1))
        sub = await t.spawn_child('lead', 'inst')
        await t.execute_tool('unknown_tool', {}, sub)
        assert seen == []
        await t.execute_tool('unknown_tool', {}, t.lead)
        assert seen == [1]

    asyncio.run(main())


def test_no_hooks_short_circuit(team):
    async def main():
        t = team(hooks=False)
        seen = []
        t.hooks.on('UserPromptSubmit', fn=_watch(seen, lambda _: 1))
        ans = await t.query('go')
        assert ans == 'ok'
        assert seen == []

    asyncio.run(main())


def test_a_stop_hook_can_end_the_session(team):
    async def main():
        t = team()
        events = []
        off = register_runtime_handler(
            lambda ev: events.append(ev) if ev.kind == AGENT_WARN else None)
        t.hooks.on('Stop', fn=lambda inp: {'continue': False,
                                           'stopReason': 'the hook called it'})
        await t.query('go')
        off()
        return t, events

    t, events = asyncio.run(main())
    assert t.lead._stop.is_set()
    assert 'the hook called it' in str([e.data.get('text') for e in events])


def test_a_hook_warning_reaches_the_user(team):
    seen = []

    async def main():
        t = team()
        off = register_runtime_handler(
            lambda ev: seen.append(ev.data.get('text'))
            if ev.kind == AGENT_WARN else None)
        t.hooks.on('UserPromptSubmit', fn=lambda inp: {
            'systemMessage': 'memory is nearly full'})
        out = await t.query('go')
        off()
        return out

    asyncio.run(main())
    assert 'memory is nearly full' in seen


def test_a_hook_answering_for_the_wrong_event_is_reported(team):
    agg = asyncio.run(_run_pre_tool_hook(
        team, _output('PostToolUse', additionalContext='x')))
    assert agg.results[0].outcome == 'non_blocking_error'
    assert 'PostToolUse' in agg.results[0].message


def test_a_permission_request_hook_sees_the_tool_and_suggestions(team):
    seen = []

    async def main():
        t = team()
        t.hooks.register('PermissionRequest', fn=lambda inp: (
            seen.append(inp),
            _output('PermissionRequest',
                    decision={'behavior': 'allow',
                              'updatedInput': {'command': 'ls'}}))[1])
        return await t.hooks.execute_permission_request_hooks(
            t.lead, 'Bash', {'command': 'ls -la'}, tool_use_id='u1',
            permission_suggestions=['Bash(ls:*)'])

    agg = asyncio.run(main())
    assert seen[0]['tool_name'] == 'Bash'
    assert seen[0]['tool_use_id'] == 'u1'
    assert seen[0]['permission_suggestions'] == ['Bash(ls:*)']
    assert agg.decision == 'allow'
    assert agg.updated_input == {'command': 'ls'}
    assert agg.blocking_error is None


def test_clearing_the_session_reopens_it_without_running_setup_again(team):
    seen = []

    async def main():
        t = team()
        t.hooks.on('Setup', fn=_watch(seen, lambda inp: ('setup', inp['trigger'])))
        t.hooks.on('SessionStart', fn=_watch(seen, lambda inp: ('start', inp['source'])))
        t.hooks.on('SessionEnd', fn=_watch(seen, lambda inp: ('end', inp['reason'])))
        await t.query('one')
        await t.end_session('clear')
        t.begin_new_session('clear')
        await t.query('two')

    asyncio.run(main())
    assert seen == [('setup', 'init'), ('start', 'startup'),
                    ('end', 'clear'), ('start', 'clear')]


def test_permission_mode_is_reported_once_the_host_knows_it(team):
    seen = []

    async def main():
        t = team()
        t.hooks.permission_mode = 'plan'
        t.hooks.on('PreToolUse',
                   fn=_watch(seen,
                             lambda inp: inp.get('permission_mode', 'missing')))
        await t.hooks.execute_pre_tool_hooks(t.lead, 't1', 'Bash', {})
        t.hooks.permission_mode = ''
        await t.hooks.execute_pre_tool_hooks(t.lead, 't2', 'Bash', {})

    asyncio.run(main())
    assert seen == ['plan', 'missing']


def test_a_writing_tool_fires_file_changed_with_the_resolved_path(tmp_path):
    import asyncio
    from pathlib import Path

    from chatchat.tool import ToolContext, tool

    from helpers import mock_team
    written = tmp_path / 'workspace' / 'note.txt'
    seen = []

    @tool(name='Note', description='write a note file',
          read_only=False, get_path=lambda args: args['file_path'],
          parameters={'type': 'object', 'properties': {
              'file_path': {'type': 'string'}}})
    async def Note(context, file_path):
        path = Path(context.cwd) / file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('noted\n', encoding='utf-8')
        return 'ok'

    @tool(name='Peek', description='read a note file', read_only=True,
          get_path=lambda args: args['file_path'])
    async def Peek(context, file_path):
        return 'contents'

    async def main():
        t = mock_team('files', tools=[Note, Peek],
                      tool_context=ToolContext(cwd=tmp_path / 'workspace'))
        t.hooks.register('FileChanged', '*', fn=_watch(seen))
        await t.execute_tool('Peek', {'file_path': 'note.txt'}, t.lead)
        await t.execute_tool('Note', {'file_path': 'note.txt'}, t.lead)
        await t.execute_tool('Note', {'file_path': '../outside.txt'}, t.lead)
        return t

    asyncio.run(main())
    assert [entry['file_path'] for entry in seen] == [str(written)]


def test_a_hook_event_handler_can_be_taken_away_again():
    from chatchat.hooks import events

    saved = events._event_handler
    events._pending_events.clear()
    seen = []
    unregister = events.register_hook_event_handler(seen.append)
    events.emit_started('id1', 'npm test', 'PreToolUse')
    assert len(seen) == 1
    unregister()
    events.emit_started('id2', 'npm test', 'PreToolUse')
    assert len(seen) == 1
    other = []
    second = events.register_hook_event_handler(other.append)
    assert [event.hook_id for event in other] == ['id2']
    second()
    events._pending_events.clear()
    events._event_handler = saved


def test_the_manager_lists_configured_hooks_with_their_source(team):
    import asyncio

    async def main():
        t = team()
        t.hooks.on('PreToolUse', 'Bash', fn=lambda inp: True)
        return t.hooks.configured()

    rows = asyncio.run(main())
    session = [row for row in rows if row['source'] == 'sessionHook']
    assert session[0]['event'] == 'PreToolUse'
    assert session[0]['matcher'] == 'Bash'
    assert session[0]['type'] == 'function'
