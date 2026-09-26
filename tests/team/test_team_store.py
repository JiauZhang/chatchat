"""A team is both a directory and a task list, so joining one has to move both."""
import asyncio
import json

import pytest
from chatchat.team.team_store import TeamStore
from chatchat.tool import ToolContext
from helpers import mock_team


def _store(tmp_path):
    return TeamStore(tmp_path / 'teams')


def test_a_created_team_can_be_found_again(tmp_path):
    store = _store(tmp_path)
    store.create('parser', 'rework the parser', leader='s1')
    assert store.exists('parser')
    record = store.read('parser')
    assert record['description'] == 'rework the parser'
    assert [row['name'] for row in store.list()] == ['parser']
    assert store.list(leader='other') == []


def test_members_are_listed_until_they_are_dropped(tmp_path):
    store = _store(tmp_path)
    store.create('parser')
    store.note_member('parser', {'agent_id': 'a@parser', 'name': 'a'})
    store.note_member('parser', {'agent_id': 'b@parser', 'name': 'b'})
    assert sorted(member['name'] for member in store.members('parser')) == \
        ['a', 'b']
    store.drop_member('parser', 'a@parser')
    assert [member['name'] for member in store.members('parser')] == ['b']


def test_creating_the_same_team_twice_is_refused(tmp_path):
    store = _store(tmp_path)
    store.create('parser')
    with pytest.raises(ValueError):
        store.create('parser')
    assert store.read('parser') is not None


def test_deleting_a_team_takes_its_record_away(tmp_path):
    store = _store(tmp_path)
    store.create('parser')
    store.delete('parser')
    assert store.read('parser') is None
    assert not (tmp_path / 'teams' / 'parser').exists()


def test_a_team_name_cannot_walk_out_of_the_store(tmp_path):
    store = _store(tmp_path)
    store.create('../../escape')
    assert not (tmp_path / 'escape').exists()
    assert store.read('../../escape') is None or list(
        (tmp_path / 'teams').iterdir())


def test_joining_a_team_moves_the_task_list_with_it(tmp_path):
    async def answer(messages, tools=None, *, stream_cb=None):
        return 'ok'

    async def main():
        team = mock_team('pyclaw-1', handler=answer,
                         tasks_dir=tmp_path / 'tasks',
                         mailbox_dir=tmp_path / 'mailboxes',
                         file_history_dir=tmp_path / 'history',
                         team_store=tmp_path / 'teams',
                         tool_context=ToolContext(cwd=tmp_path))
        await team.query('first')
        team.join_team('parser', 'rework the parser')
        task = team.tasks.create('read', 'the file')
        return team, task

    team, task = asyncio.run(main())
    assert team.name == 'parser'
    assert team.tasks.directory.name == 'parser'
    assert (tmp_path / 'tasks' / 'parser' / f'{task.id}.json').exists()
    assert team.mailbox_path('worker').parent.parent.name == 'parser'
    assert team.file_history.directory == tmp_path / 'history'


def test_a_task_list_touches_nothing_until_a_task_exists(tmp_path):
    from chatchat.tasks.tasks import TaskList
    tasks = TaskList(tmp_path / 'tasks' / 'pyclaw-9')
    assert tasks.all() == []
    assert tasks.get('1') is None
    assert not (tmp_path / 'tasks').exists()
    tasks.create('read', 'the file')
    assert (tmp_path / 'tasks' / 'pyclaw-9' / '1.json').exists()


def test_a_taken_team_name_becomes_a_unique_one(tmp_path):
    async def main():
        first = mock_team('pyclaw-2', team_store=tmp_path / 'teams',
                          mailbox_dir=tmp_path / 'mailboxes')
        first.join_team('parser')
        second = mock_team('pyclaw-3', team_store=tmp_path / 'teams',
                           mailbox_dir=tmp_path / 'mailboxes')
        second.join_team('parser')
        return second.name

    name = asyncio.run(main())
    assert name == 'parser-2'
    names = [item['name'] for item in TeamStore(tmp_path / 'teams').list()]
    assert names == ['parser', 'parser-2']


def test_a_persisted_team_records_the_leader_conversation(tmp_path):
    async def main():
        team = mock_team('pyclaw-4', team_store=tmp_path / 'teams',
                         mailbox_dir=tmp_path / 'mailboxes')
        team.lead_session_id = 'conv-42'
        team.join_team('parser')
        return TeamStore(tmp_path / 'teams').read('parser')

    assert asyncio.run(main())['lead_session_id'] == 'conv-42'


def test_teammates_are_recorded_while_the_team_lives(tmp_path):
    store_dir = None

    async def main():
        team = mock_team('pyclaw-5', team_store=(store_dir := tmp_path / 'teams'),
                         mailbox_dir=tmp_path / 'mailboxes')
        team.join_team('parser')
        worker = team.create_agent('worker', instruction='do work')
        store = TeamStore(store_dir)
        listed = [member['name'] for member in store.members('parser')]
        await team.stop_agent(worker)
        after = [member['name'] for member in store.members('parser')]
        team.leave_team()
        return listed, after, team

    listed, after, team = asyncio.run(main())
    assert listed == ['worker']
    assert after == []
    assert team.team_context is None
    assert not (tmp_path / 'teams' / 'parser').exists()


def test_a_team_cannot_be_joined_twice(tmp_path):
    async def main():
        team = mock_team('pyclaw-2', team_store=tmp_path / 'teams')
        team.join_team('parser')
        try:
            team.join_team('other')
        except ValueError as exc:
            return team, exc
        return team, None

    team, error = asyncio.run(main())
    assert error is not None and 'already' in str(error)
    assert team.name == 'parser'


def test_a_team_with_a_live_teammate_cannot_be_left(tmp_path):
    async def main():
        team = mock_team('pyclaw-3', team_store=tmp_path / 'teams',
                         mailbox_dir=tmp_path / 'mailboxes')
        team.join_team('parser')
        team.create_agent('worker', instruction='do work')
        blocked = None
        try:
            team.leave_team()
        except ValueError as exc:
            blocked = str(exc)
        worker = team.get_by_name('worker')
        await team.stop_agent(worker)
        team.leave_team()
        return blocked, team

    blocked, team = asyncio.run(main())
    assert blocked and 'worker' in blocked
    assert team.team_context is None


def test_the_team_tools_are_offered_only_in_team_mode(tmp_path):
    async def main():
        solo = mock_team('solo', multi_agent=False,
                         team_store=tmp_path / 'teams')
        squad = mock_team('squad', multi_agent=True,
                          team_store=tmp_path / 'teams')
        return ([schema['name'] for schema in solo.tool_schemas(solo.tool_context)],
                [schema['name'] for schema in squad.tool_schemas(squad.tool_context)])

    solo, squad = asyncio.run(main())
    assert 'TeamCreate' not in solo
    assert {'TeamCreate', 'TeamDelete'} <= set(squad)


def test_the_lead_can_create_and_delete_its_team(tmp_path):
    async def main():
        team = mock_team('pyclaw-4', team_store=tmp_path / 'teams',
                         tasks_dir=tmp_path / 'tasks')
        created = await team.execute_tool(
            'TeamCreate', {'team_name': 'parser',
                            'description': 'rework the parser'}, team.lead)
        listed = json.loads((tmp_path / 'teams' / 'parser'
                             / 'config.json').read_text())
        deleted = await team.execute_tool('TeamDelete', {}, team.lead)
        refused = await team.execute_tool('TeamCreate', {}, team.lead)
        return created.text, listed, deleted.text, refused.text

    created, listed, deleted, refused = asyncio.run(main())
    assert 'parser' in created
    assert listed['description'] == 'rework the parser'
    assert not (tmp_path / 'teams' / 'parser').exists()
    assert 'Cleaned up' in deleted
    assert 'team_name' in refused
