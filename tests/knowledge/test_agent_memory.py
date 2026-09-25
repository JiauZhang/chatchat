"""An agent type can keep its own notes between runs, in one of three places."""
import asyncio
from pathlib import Path

from chatchat.knowledge.agent_memory import AgentMemory


def _memory(tmp_path, snapshots=None):
    return AgentMemory(
        roots={'user': tmp_path / 'home' / 'agent-memory',
               'project': tmp_path / 'ws' / '.pyclaw' / 'agent-memory',
               'local': tmp_path / 'ws' / '.pyclaw' / 'agent-memory-local'},
        snapshots=snapshots)


def _write(directory, text):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'MEMORY.md').write_text(text, encoding='utf-8')


def _snapshot(root, agent_type, text, when):
    directory = root / agent_type
    _write(directory, text)
    (directory / 'snapshot.json').write_text(
        f'{{"updatedAt": "{when}"}}', encoding='utf-8')
    return directory


def test_each_scope_has_its_own_directory_for_one_agent_type(tmp_path):
    memory = _memory(tmp_path)
    assert memory.directory('reviewer', 'user').name == 'reviewer'
    assert memory.directory('reviewer', 'user').parent == (
        tmp_path / 'home' / 'agent-memory')
    assert memory.directory('reviewer', 'project') != (
        memory.directory('reviewer', 'local'))
    assert memory.directory('a:b', 'user').name == 'a-b'


def test_the_prompt_carries_what_was_stored_and_where_it_lives(tmp_path):
    memory = _memory(tmp_path)
    _write(memory.directory('reviewer', 'project'),
           '## MEMORY.md\n\n- this repo lints with ruff\n')
    text = memory.prompt('reviewer', 'project')
    assert 'this repo lints with ruff' in text
    assert str(memory.directory('reviewer', 'project')) in text
    assert memory.directory('reviewer', 'project').is_dir()


def test_an_agent_without_notes_is_told_there_are_none_yet(tmp_path):
    memory = _memory(tmp_path)
    text = memory.prompt('reviewer', 'user')
    assert 'empty' in text


def test_a_long_entrypoint_is_cut_at_the_line_cap(tmp_path):
    memory = _memory(tmp_path)
    _write(memory.directory('reviewer', 'user'),
           '\n'.join(f'line {index}' for index in range(400)))
    text = memory.prompt('reviewer', 'user')
    assert 'line 199' in text
    assert 'line 200' not in text


def _snapshot(root, agent_type, text, when='2026-01-01T00:00:00Z'):
    _write(root / agent_type, text)
    (root / agent_type / 'snapshot.json').write_text(
        f'{{"updatedAt": "{when}"}}', encoding='utf-8')


def test_a_first_snapshot_run_seeds_the_local_notes(tmp_path):
    snapshots = tmp_path / 'ws' / '.pyclaw' / 'agent-memory-snapshots'
    _snapshot(snapshots, 'reviewer', 'snapshot note')
    memory = _memory(tmp_path, snapshots=snapshots)
    assert memory.sync_snapshot('reviewer', 'user') == 'initialized'
    assert 'snapshot note' in (
        memory.directory('reviewer', 'user') / 'MEMORY.md').read_text()
    assert memory.sync_snapshot('reviewer', 'user') == 'none'


def test_a_newer_snapshot_is_offered_rather_than_applied(tmp_path):
    snapshots = tmp_path / 'ws' / '.pyclaw' / 'agent-memory-snapshots'
    _snapshot(snapshots, 'reviewer', 'first')
    memory = _memory(tmp_path, snapshots=snapshots)
    memory.sync_snapshot('reviewer', 'user')
    _snapshot(snapshots, 'reviewer', 'second', when='2026-01-02T00:00:00Z')
    assert memory.sync_snapshot('reviewer', 'user') == 'update'
    assert 'first' in (memory.directory('reviewer', 'user')
                       / 'MEMORY.md').read_text()


def test_apply_the_snapshot_replaces_the_notes_it_had(tmp_path):
    snapshots = tmp_path / 'ws' / '.pyclaw' / 'agent-memory-snapshots'
    _snapshot(snapshots, 'reviewer', 'first')
    memory = _memory(tmp_path, snapshots=snapshots)
    memory.sync_snapshot('reviewer', 'user')
    _snapshot(snapshots, 'reviewer', 'second', when='2026-01-02T00:00:00Z')
    assert memory.apply_snapshot('reviewer', 'user') == 'applied'
    held = (memory.directory('reviewer', 'user') / 'MEMORY.md').read_text()
    assert 'second' in held and 'first' not in held


def test_without_a_published_snapshot_there_is_nothing_to_sync(tmp_path):
    snapshots = tmp_path / 'ws' / '.pyclaw' / 'agent-memory-snapshots'
    (snapshots / 'reviewer').mkdir(parents=True)
    assert _memory(tmp_path).sync_snapshot('reviewer', 'user') == 'none'
    assert _memory(tmp_path, snapshots=snapshots).sync_snapshot(
        'reviewer', 'user') == 'none'


def test_writing_into_any_memory_root_needs_no_approval(tmp_path):
    memory = _memory(tmp_path)
    inside = memory.directory('reviewer', 'project') / 'notes.md'
    assert memory.contains(Path(inside)) is True
    assert memory.contains(tmp_path / 'ws' / 'app.py') is False


def _spawned(team, agent_type):
    return team.agents[next(iter(
        agent_id for agent_id in team.agents
        if agent_id != team.lead.agent_id))].instruction


def test_an_agent_with_a_memory_scope_starts_with_its_notes(tmp_path):
    from helpers import mock_team

    async def main():
        team = mock_team('mem1')
        team.agent_memory = _memory(tmp_path)
        team.agent_memory.directory('reviewer', 'project').mkdir(parents=True,
                                                                  exist_ok=True)
        (team.agent_memory.directory('reviewer', 'project')
         / 'MEMORY.md').write_text('- prefer pytest', encoding='utf-8')
        team.agent_defs.define('reviewer', system_prompt='review it',
                               memory='project')
        await team.spawn_subagent('look at this', subagent_type='reviewer')
        return _spawned(team, 'reviewer')

    instruction = asyncio.run(main())
    assert 'prefer pytest' in instruction
    assert instruction.startswith('review it')


def test_an_agent_without_a_scope_starts_with_no_notes(tmp_path):
    from helpers import mock_team

    async def main():
        team = mock_team('mem2')
        team.agent_memory = _memory(tmp_path)
        team.agent_defs.define('plain', system_prompt='do it')
        await team.spawn_subagent('look at this', subagent_type='plain')
        return _spawned(team, 'plain')

    assert asyncio.run(main()) == 'do it'
