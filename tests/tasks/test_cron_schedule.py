"""Scheduled prompts have to survive a restart, spread out, and stay one per project."""
import json
from datetime import datetime, timedelta

from chatchat.tasks.cron import parse
from chatchat.tasks.cron_schedule import (CronStore, Jitter, SchedulerLock,
                                          expired, find_missed, next_fire)


def _store(tmp_path):
    return CronStore(tmp_path / 'project' / '.pyclaw')


def test_a_durable_task_is_written_and_a_session_task_is_not(tmp_path):
    store = _store(tmp_path)
    pinned = store.add('30 14 * * *', 'stand up', recurring=False, durable=True)
    quiet = store.add('*/5 * * * *', 'check the build', recurring=True,
                      durable=False)
    assert [task['id'] for task in store.durable()] == [pinned['id']]
    assert [task['id'] for task in store.session()] == [quiet['id']]
    assert (store.path.exists()
            and pinned['id'] in store.path.read_text(encoding='utf-8'))
    assert store.all() == [pinned, quiet]


def test_a_task_read_back_keeps_the_fields_that_computed_its_next_fire(tmp_path):
    store = _store(tmp_path)
    added = store.add('0 9 * * 1', 'weekly', recurring=True, durable=True)
    store.mark_fired(added['id'], datetime(2026, 5, 4, 9, 0))
    held = CronStore(tmp_path / 'project' / '.pyclaw').durable()[0]
    assert held['last_fired_at'] == '2026-05-04T09:00:00'
    assert held['recurring'] is True


def test_a_broken_entry_does_not_take_the_rest_of_the_file_with_it(tmp_path):
    store = _store(tmp_path)
    kept = store.add('0 8 * * *', 'keep me', recurring=True, durable=True)
    body = json.loads(store.path.read_text(encoding='utf-8'))
    body['tasks'] += [{'id': 'junk'},
                      {'id': 'bad', 'cron': '99 * * * *',
                       'prompt': 'no', 'created_at': '2026-05-04T08:00:00'}]
    store.path.write_text(json.dumps(body), encoding='utf-8')
    assert [task['id'] for task in store.durable()] == [kept['id']]


def test_removing_a_task_takes_it_off_disk(tmp_path):
    store = _store(tmp_path)
    added = store.add('0 8 * * *', 'gone soon', recurring=True, durable=True)
    assert store.remove(added['id'])['prompt'] == 'gone soon'
    assert store.durable() == []
    assert store.remove(added['id']) is None


def test_the_job_list_stops_growing_at_the_cap(tmp_path):
    store = _store(tmp_path)
    for index in range(store.MAX_JOBS):
        store.add(f'{index % 60} * * * *', f'job {index}', recurring=True,
                  durable=True)
    extra = store.add('0 * * * *', 'one too many', recurring=True, durable=True)
    assert extra is None
    assert store.refused == f'too many scheduled jobs (max {store.MAX_JOBS})'


def test_only_one_session_in_a_project_runs_the_file(tmp_path):
    directory = tmp_path / 'project' / '.pyclaw'
    mine = SchedulerLock(directory, 'session-a')
    other = SchedulerLock(directory, 'session-b')
    assert mine.acquire() is True
    assert other.acquire() is False
    assert other.held_by()['session_id'] == 'session-a'
    mine.release()
    assert other.acquire() is True


def test_a_lock_left_behind_by_a_dead_process_is_taken_over(tmp_path):
    directory = tmp_path / 'project' / '.pyclaw'
    directory.mkdir(parents=True)
    (directory / 'scheduled_tasks.lock').write_text(
        json.dumps({'pid': 2_000_000, 'session_id': 'gone'}), encoding='utf-8')
    fresh = SchedulerLock(directory, 'session-c')
    assert fresh.acquire() is True


def _pinned(task: dict, created_at: str) -> dict:
    return {**task, 'created_at': created_at}


def test_the_recurring_fire_is_spread_by_a_stable_amount(tmp_path):
    store = _store(tmp_path)
    first = _pinned(store.add('0 * * * *', 'hourly', durable=False),
                    '2026-05-04T09:00:00')
    second = _pinned(store.add('0 * * * *', 'hourly too', durable=False),
                     '2026-05-04T09:00:00')
    second['id'] = 'ffffffff'
    now = datetime(2026, 5, 4, 9, 30)
    mark = datetime(2026, 5, 4, 10, 0)
    fired = next_fire(first, now)
    assert mark <= fired <= mark + timedelta(minutes=15)
    assert fired != next_fire(second, now)
    assert next_fire(first, now) == fired
    store.mark_fired(first['id'], fired)
    held = store.session()[0]
    following = next_fire(held, fired)
    assert datetime(2026, 5, 4, 11, 0) <= following <= (
        datetime(2026, 5, 4, 11, 0) + timedelta(minutes=15))


def test_a_one_shot_fires_on_the_minute_the_user_asked_for(tmp_path):
    store = _store(tmp_path)
    odd = _pinned(store.add('7 15 * * *', 'at three past three',
                            recurring=False, durable=False),
                  '2026-05-04T09:00:00')
    assert next_fire(odd, datetime(2026, 5, 4, 9, 30)) == datetime(
        2026, 5, 4, 15, 7)


def test_a_one_shot_on_a_round_minute_leads_slightly(tmp_path):
    store = _store(tmp_path)
    pinned = _pinned(store.add('0 15 * * *', 'at three', recurring=False, durable=False),
                     '2026-05-04T09:00:00')
    fired = next_fire(pinned, datetime(2026, 5, 4, 9, 30))
    mark = datetime(2026, 5, 4, 15, 0)
    assert fired <= mark
    assert mark - fired <= timedelta(seconds=90)


def test_a_task_created_inside_its_own_lead_window_does_not_fire_backwards(
        tmp_path):
    store = _store(tmp_path)
    late = _pinned(store.add('0 15 * * *', 'at three', recurring=False, durable=False),
                   '2026-05-04T14:00:00')
    now = datetime(2026, 5, 4, 14, 59, 50)
    assert next_fire(late, now) >= now


def test_recurring_work_ages_out(tmp_path):
    store = _store(tmp_path)
    old = store.add('0 * * * *', 'ancient', recurring=True, durable=False)
    now = datetime(2026, 5, 4, 10, 0)
    assert expired(old, now) is False
    old['created_at'] = (now - timedelta(days=8)).isoformat()
    assert expired(old, now) is True
    assert expired({**old, 'permanent': True}, now) is False
    assert expired({**old, 'recurring': False}, now) is False


def test_work_missed_while_the_process_was_down_is_found():
    tasks = [{'id': 'a', 'cron': '0 9 * * *', 'prompt': 'morning',
              'created_at': '2026-05-01T08:00:00', 'recurring': True},
             {'id': 'b', 'cron': '0 9 1 1 *', 'prompt': 'far off',
              'created_at': '2026-05-01T08:00:00'}]
    missed = find_missed(tasks, datetime(2026, 5, 4, 10, 0))
    assert [task['id'] for task in missed] == ['a']


def test_the_jitter_reads_its_own_configuration():
    cfg = Jitter(recurring_cap=0.0)
    task = {'id': 'abcd1234', 'cron': '0 * * * *', 'prompt': 'x',
            'created_at': '2026-05-04T09:00:00', 'recurring': True}
    assert next_fire(task, datetime(2026, 5, 4, 9, 30), cfg) == datetime(
        2026, 5, 4, 10, 0)


def _tools(team):
    return [schema['name'] for schema in team.tool_schemas(team.tool_context)]


def test_the_cron_tools_appear_only_once_a_schedule_exists():
    import asyncio

    from helpers import mock_team

    async def main():
        team = mock_team('cron1')
        before = _tools(team)
        from chatchat.tasks.cron_schedule import CronStore
        team.cron = CronStore('unused')
        return before, _tools(team)

    before, after = asyncio.run(main())
    assert 'CronCreate' not in before
    assert {'CronCreate', 'CronList', 'CronDelete'} <= set(after)


def test_a_scheduled_prompt_can_be_listed_and_cancelled():
    import asyncio
    import tempfile

    from helpers import mock_team

    async def main():
        team = mock_team('cron2')
        with tempfile.TemporaryDirectory() as directory:
            from chatchat.tasks.cron_schedule import CronStore
            team.cron = CronStore(directory)
            created = await team.execute_tool(
                'CronCreate', {'cron': '0 9 * * *',
                                'prompt': 'check the builds'}, team.lead)
            listed = await team.execute_tool('CronList', {}, team.lead)
            ident = created.text.split()[2].rstrip(':')
            deleted = await team.execute_tool('CronDelete', {'id': ident},
                                              team.lead)
            after = await team.execute_tool('CronList', {}, team.lead)
        return created.text, listed.text, deleted.text, after.text

    created, listed, deleted, after = asyncio.run(main())
    assert '09:00' in created and 'check the builds' in created
    assert 'check the builds' in listed
    assert 'cancelled' in deleted
    assert after == 'Nothing scheduled.'


def test_a_broken_cron_string_is_refused_before_it_is_stored():
    import asyncio
    import tempfile

    from helpers import mock_team

    async def main():
        team = mock_team('cron3')
        with tempfile.TemporaryDirectory() as directory:
            from chatchat.tasks.cron_schedule import CronStore
            team.cron = CronStore(directory)
            return await team.execute_tool(
                'CronCreate', {'cron': '99 * * * *', 'prompt': 'never'},
                team.lead)

    outcome = asyncio.run(main())
    assert outcome.text.startswith('Error:')
    assert outcome.text == 'Error: invalid cron expression: 99 * * * *'
