import asyncio
import json

from chatchat.core.tasks import Claim, TaskItem, TaskList, work_prompt
from helpers import mock_team


def _list(tmp_path):
    return TaskList(tmp_path / 'tasks' / 'swarm')


def test_tasks_are_created_with_a_numbered_id_and_no_owner(tmp_path):
    tasks = _list(tmp_path)
    first = tasks.create('Fix login', 'the form posts nowhere')
    second = tasks.create('Fix logout', 'nothing clears')

    assert (first.id, second.id) == ('1', '2')
    assert first.status == 'pending'
    assert first.owner == ''
    assert second.subject == 'Fix logout'


def test_ids_are_never_reused_after_a_delete(tmp_path):
    tasks = _list(tmp_path)
    created = tasks.create('gone', 'soon')
    assert tasks.delete(created.id) is True
    assert tasks.create('next', 'after a delete').id == '2'


def test_a_second_list_sees_the_same_files(tmp_path):
    tasks = _list(tmp_path)
    other = _list(tmp_path)
    tasks.create('shared', 'written by one reader')
    assert [t.subject for t in other.all()] == ['shared']


def test_updates_keep_the_fields_that_were_not_sent(tmp_path):
    tasks = _list(tmp_path)
    task = tasks.create('Ship it', 'carefully', active_form='Shipping')
    updated = tasks.update(task.id, status='in_progress', owner='worker')

    assert updated.status == 'in_progress'
    assert updated.owner == 'worker'
    assert updated.active_form == 'Shipping'
    assert updated.description == 'carefully'


def test_an_unknown_task_or_status_is_not_a_write(tmp_path):
    tasks = _list(tmp_path)
    task = tasks.create('keep me', 'untouched')

    assert tasks.get('404') is None
    assert tasks.update('404', status='pending') is None
    assert tasks.update(task.id, status='done') is None
    assert tasks.get(task.id).status == 'pending'


def test_deleting_a_task_removes_it_from_the_graph(tmp_path):
    tasks = _list(tmp_path)
    blocker = tasks.create('blocker', 'first')
    blocked = tasks.create('blocked', 'second')
    assert tasks.block(blocker.id, blocked.id) is True
    assert tasks.get(blocked.id).blocked_by == [blocker.id]

    assert tasks.delete(blocker.id) is True
    assert tasks.get(blocker.id) is None
    assert tasks.get(blocked.id).blocked_by == []
    assert tasks.delete('404') is False


def test_blocking_is_idempotent_and_needs_both_tasks(tmp_path):
    tasks = _list(tmp_path)
    a = tasks.create('a', 'first')
    b = tasks.create('b', 'second')
    tasks.block(a.id, b.id)
    tasks.block(a.id, b.id)

    assert tasks.get(b.id).blocked_by == ['1']
    assert tasks.get(a.id).blocks == ['2']
    assert tasks.block(a.id, '404') is False


def test_a_claimant_takes_an_unblocked_pending_task(tmp_path):
    tasks = _list(tmp_path)
    task = tasks.create('claim me', 'please')
    result = tasks.claim(task.id, 'worker@team')

    assert isinstance(result, Claim) and result.ok
    assert result.task.owner == 'worker@team'


def test_claims_are_refused_for_a_reason(tmp_path):
    tasks = _list(tmp_path)
    taken = tasks.create('taken', 'by someone else')
    tasks.claim(taken.id, 'worker@team')
    done = tasks.create('finished', 'already')
    tasks.update(done.id, status='completed')
    blocker = tasks.create('blocker', 'holds the line')
    waiting = tasks.create('waiting', 'cannot start')
    tasks.block(blocker.id, waiting.id)

    assert tasks.claim('404', 'other@team').reason == 'task_not_found'
    assert tasks.claim(taken.id, 'other@team').reason == 'already_claimed'
    assert tasks.claim(taken.id, 'worker@team').ok is True
    assert tasks.claim(done.id, 'other@team').reason == 'already_resolved'
    blocked = tasks.claim(waiting.id, 'other@team')
    assert (blocked.reason, blocked.blocked_by) == ('blocked', ['3'])


def test_a_busy_agent_can_wait_for_its_current_task(tmp_path):
    tasks = _list(tmp_path)
    busy_with = tasks.create('one open task', 'in hand')
    tasks.claim(busy_with.id, 'worker@team')
    next_up = tasks.create('another', 'later')

    refused = tasks.claim(next_up.id, 'worker@team', check_agent_busy=True)
    assert (refused.reason, refused.busy_with) == ('agent_busy', ['1'])
    tasks.update(busy_with.id, status='completed')
    assert tasks.claim(next_up.id, 'worker@team',
                       check_agent_busy=True).ok is True


def test_open_tasks_of_a_leaving_agent_are_handed_back(tmp_path):
    tasks = _list(tmp_path)
    kept = tasks.create('finished work', 'done')
    loose = tasks.create('unfinished work', 'still open')
    tasks.claim(kept.id, 'worker@team')
    tasks.claim(loose.id, 'worker@team')
    tasks.update(kept.id, status='completed')

    released = tasks.unassign('worker@team', 'worker')
    assert [t.id for t in released] == [loose.id]
    assert tasks.get(loose.id).owner == ''
    assert tasks.get(loose.id).status == 'pending'
    assert tasks.get(kept.id).owner == 'worker@team'


def test_an_id_that_looks_like_a_path_cannot_escape_the_directory(tmp_path):
    tasks = _list(tmp_path)
    tasks.create('safe', 'inside')

    assert tasks.get('../../etc/passwd') is None
    assert tasks.update('../x', status='pending') is None
    assert (tasks.directory / '1.json').exists()
    assert not (tmp_path / 'etc').exists()


def test_the_task_file_is_the_only_state(tmp_path):
    tasks = _list(tmp_path)
    tasks.create('from json', 'written once', metadata={'kind': 'test'})
    record = json.loads((tasks.directory / '1.json').read_text())

    assert record['subject'] == 'from json'
    assert record['metadata'] == {'kind': 'test'}
    assert TaskItem.from_dict(record).metadata == {'kind': 'test'}


def _run(calls, tmp_path, *, with_names=False, tasks=True):
    async def main():
        team = mock_team(
            'tk', tasks_dir=tmp_path / 'tasks' if tasks else None,
            mailbox_dir=tmp_path / 'mailboxes' if tasks else None)
        out = [(await team.execute_tool(name, args, team.lead)).text
               for name, args in calls]
        if with_names:
            out.append([t['name']
                        for t in team.tool_schemas(team.tool_context)])
        return team, out

    return asyncio.run(main())


def test_the_task_tools_are_offered_and_write_the_shared_list(tmp_path):
    team, (made, listed, got, moved, names) = _run([
        ('task_create', {'subject': 'Do it', 'description': 'and verify'}),
        ('task_list', {}),
        ('task_get', {'task_id': '1'}),
        ('task_update', {'task_id': '1', 'status': 'completed'}),
    ], tmp_path, with_names=True)

    assert {'task_create', 'task_update', 'task_list',
            'task_get'} <= set(names)
    assert made.startswith('Task #1 created')
    assert listed == '#1 [pending] Do it'
    assert got.startswith('Task #1: Do it') and 'and verify' in got
    assert 'status -> completed' in moved
    assert team.tasks.get('1').status == 'completed'


def test_a_task_tool_reports_a_bad_request_instead_of_raising(tmp_path):
    _, (noid, missing, no_subject, nothing) = _run([
        ('task_update', {'status': 'pending'}),
        ('task_get', {'task_id': '77'}),
        ('task_create', {'subject': 'x'}),
        ('task_update', {'task_id': '1'}),
    ], tmp_path)

    assert 'task_id' in noid
    assert 'not found' in missing
    assert 'description' in no_subject
    assert 'nothing to change' in nothing


def test_task_list_marks_who_owns_a_task_and_what_holds_it(tmp_path):
    _, (_, _, updated, listed) = _run([
        ('task_create', {'subject': 'First', 'description': 'a'}),
        ('task_create', {'subject': 'Second', 'description': 'b'}),
        ('task_update', {'task_id': '2', 'owner': 'worker',
                         'add_blocked_by': ['1']}),
        ('task_list', {}),
    ], tmp_path)

    assert 'add_blocked_by' in updated
    assert listed == ('#1 [pending] First\n'
                      '#2 [pending] Second (worker) [blocked by #1]')


def test_updating_a_task_can_delete_it(tmp_path):
    team, (created, moved, listed) = _run([
        ('task_create', {'subject': 'Drop me', 'description': 'x'}),
        ('task_update', {'task_id': '1', 'status': 'deleted'}),
        ('task_list', {}),
    ], tmp_path)

    assert created.startswith('Task #1 created')
    assert moved == 'Task #1 deleted'
    assert listed == 'No tasks yet'
    assert team.tasks.all() == []


def test_metadata_merges_and_a_null_key_is_dropped(tmp_path):
    team, (_, moved) = _run([
        ('task_create', {'subject': 'Tagged', 'description': 'x',
                         'metadata': {'kind': 'test', 'stale': 1}}),
        ('task_update', {'task_id': '1',
                         'metadata': {'kind': 'other', 'stale': None}}),
    ], tmp_path)

    assert team.tasks.get('1').metadata == {'kind': 'other'}
    assert 'metadata' in moved


def test_a_team_without_a_task_list_has_no_task_tools(tmp_path):
    _, (names,) = _run([], tmp_path, with_names=True, tasks=False)
    assert 'task_create' not in names
    assert 'create_agent' in names


def _queue(tmp_path, handler):
    async def main():
        team = mock_team('queue', handler=handler,
                         tasks_dir=tmp_path / 'tasks',
                         mailbox_dir=tmp_path / 'mailboxes')
        worker = team.create_agent('worker', instruction='do work')
        await worker.poller.stop()
        return team, worker

    return asyncio.run(main())


def test_an_idle_teammate_picks_up_the_next_free_task(tmp_path):
    async def work(messages, tools=None, *, stream_cb=None):
        return 'done'

    team, worker = _queue(tmp_path, work)
    first = team.tasks.create('Write the tests', 'cover the parser')
    prompt = asyncio.run(worker._next_task())

    assert prompt.startswith(f'Work on task #{first.id}: Write the tests')
    assert 'cover the parser' in prompt
    claimed = team.tasks.get(first.id)
    assert (claimed.owner, claimed.status) == ('worker', 'in_progress')


def test_a_teammate_only_takes_a_task_that_is_free(tmp_path):
    async def work(messages, tools=None, *, stream_cb=None):
        return 'done'

    team, worker = _queue(tmp_path, work)
    blocker = team.tasks.create('First', 'blocks the rest')
    waiting = team.tasks.create('Second', 'cannot start yet')
    taken = team.tasks.create('Third', 'someone else has it')
    team.tasks.block(blocker.id, waiting.id)
    team.tasks.update(taken.id, owner='other')

    offered = asyncio.run(worker._next_task())
    assert f'#{blocker.id}' in offered and f'#{waiting.id}' not in offered
    assert [t.id for t in team.tasks.current_of(worker.agent_id, 'worker')] \
        == [blocker.id]
    assert team.tasks.get(waiting.id).owner == ''
    assert team.tasks.get(taken.id).owner == 'other'


def test_stopping_a_teammate_hands_its_open_tasks_back(tmp_path):
    async def work(messages, tools=None, *, stream_cb=None):
        return 'done'

    team, worker = _queue(tmp_path, work)
    held = team.tasks.create('Half done', 'still open')
    finished = team.tasks.create('All done', 'closed')
    team.tasks.claim(held.id, 'worker')
    team.tasks.claim(finished.id, 'worker')
    team.tasks.update(finished.id, status='completed')
    asyncio.run(team.stop_agent(worker))
    notice = team.lead.inbox.unread()

    assert team.tasks.get(held.id).status == 'pending'
    assert team.tasks.get(held.id).owner == ''
    assert team.tasks.get(finished.id).owner == 'worker'
    assert len(notice) == 1
    assert 'Half done' in notice[0].text
