"""The file history has to be able to put a workspace back, so every promise
the rewind dialog makes is tested here."""
from pathlib import Path

from chatchat.core.filehistory import FileHistory


def _history(tmp_path, **kw):
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    return FileHistory(directory=tmp_path / 'file-history', cwd=workspace,
                       **kw), workspace


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def test_an_edit_is_captured_before_it_happens(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'one\ntwo\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'one\nchanged\n')

    assert history.rewind(0) == ['a.py']
    assert target.read_text() == 'one\ntwo\n'


def test_a_file_the_agent_created_is_removed_again(tmp_path):
    history, ws = _history(tmp_path)
    target = ws / 'new.py'
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'brand new\n')

    assert history.rewind(0) == ['new.py']
    assert not target.exists()


def test_a_second_edit_in_the_same_turn_keeps_the_original(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'v1\n')
    history.track_edit(target)
    _write(target, 'v2\n')

    history.rewind(0)
    assert target.read_text() == 'v0\n'


def test_each_turn_keeps_its_own_version(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'v1\n')
    history.snapshot(3)
    history.track_edit(target)
    _write(target, 'v2\n')
    history.snapshot(6)

    history.rewind(3)
    assert target.read_text() == 'v1\n'
    history.rewind(0)
    assert target.read_text() == 'v0\n'
    history.rewind(6)
    assert target.read_text() == 'v2\n'


def test_a_rewind_only_touches_what_actually_differs(tmp_path):
    history, ws = _history(tmp_path)
    first = _write(ws / 'a.py', 'v0\n')
    second = _write(ws / 'b.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(first)
    history.track_edit(second)
    _write(first, 'v1\n')
    history.snapshot(3)

    assert history.rewind(0) == ['a.py']
    assert first.read_text() == 'v0\n'
    assert second.read_text() == 'v0\n'


def test_a_change_made_outside_the_agent_is_backed_up_next_turn(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'v1 by hand\n')
    history.snapshot(3)

    history.rewind(0)
    assert target.read_text() == 'v0\n'


def test_rewind_reports_the_lines_it_would_put_back(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'one\ntwo\nthree\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'one\nchanged\nthree\nextra\n')

    stats = history.diff_stats(0)
    assert stats['files'] == ['a.py']
    assert (stats['insertions'], stats['deletions']) == (1, 2)


def test_an_unknown_turn_cannot_be_restored(tmp_path):
    history, ws = _history(tmp_path)
    assert history.can_restore(0) is False
    history.snapshot(0)
    assert history.can_restore(0) is True
    assert history.can_restore(99) is False


def test_a_disabled_history_leaves_no_trace(tmp_path):
    history, ws = _history(tmp_path, enabled=False)
    target = _write(ws / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(target)

    assert history.rewind(0) == []
    assert not (tmp_path / 'file-history').exists()


def test_only_the_most_recent_turns_are_kept(tmp_path):
    history, ws = _history(tmp_path, max_snapshots=3)
    target = _write(ws / 'a.py', 'v0\n')
    for mark in range(10):
        history.snapshot(mark)
        history.track_edit(target)
        _write(target, f'v{mark + 1}\n')

    assert len(history.snapshots) == 3
    assert history.can_restore(9) is True
    assert history.can_restore(0) is False


def test_a_file_outside_the_workspace_keeps_its_absolute_key(tmp_path):
    history, ws = _history(tmp_path)
    outside = _write(tmp_path / 'elsewhere' / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(outside)
    _write(outside, 'v1\n')

    assert history.rewind(0) == [str(outside)]
    assert outside.read_text() == 'v0\n'


def test_history_survives_a_reopen_of_the_same_store(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'v0\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, 'v1\n')
    reopened = FileHistory(directory=tmp_path / 'file-history', cwd=ws)
    reopened.restore(history.dump())

    assert reopened.rewind(0) == ['a.py']
    assert target.read_text() == 'v0\n'
    assert isinstance(reopened.snapshots[-1].timestamp, str)


def test_emptying_a_file_is_a_change_not_a_no_op(tmp_path):
    history, ws = _history(tmp_path)
    target = _write(ws / 'a.py', 'content\n')
    history.snapshot(0)
    history.track_edit(target)
    _write(target, '')

    assert history.rewind(0) == ['a.py']
    assert target.read_text() == 'content\n'


def test_a_team_marks_the_history_at_the_start_of_each_turn(tmp_path):
    import asyncio

    from chatchat.tool import ToolContext

    from helpers import mock_team

    async def answer(messages, tools=None, *, stream_cb=None):
        return 'ok'

    async def main():
        workspace = tmp_path / 'ws'
        workspace.mkdir()
        team = mock_team('fh', handler=answer,
                         file_history_dir=tmp_path / 'history',
                         tool_context=ToolContext(cwd=workspace))
        await team.query('first')
        await team.query('second')
        return team

    team = asyncio.run(main())
    assert team.file_history is team.tool_context.files
    assert [snap.mark for snap in team.file_history.snapshots] == [0, 2]


def test_a_team_without_a_directory_keeps_no_history(tmp_path):
    import asyncio

    async def answer(messages, tools=None, *, stream_cb=None):
        return 'ok'

    async def main():
        from helpers import mock_team
        return mock_team('plain', handler=answer)

    team = asyncio.run(main())
    assert team.file_history is None
    assert team.tool_context.files is None


def _rewind_team(tmp_path, handler, prepare=None):
    import asyncio

    from chatchat.tool import ToolContext

    from helpers import mock_team
    workspace = tmp_path / 'ws'
    workspace.mkdir()

    async def main():
        team = mock_team('rw', handler=handler,
                         file_history_dir=tmp_path / 'history',
                         tool_context=ToolContext(cwd=workspace))
        if prepare is not None:
            prepare(team)
        await team.query('first')
        await team.query('second')
        return team, workspace

    return asyncio.run(main())


def test_rewinding_a_turn_can_put_the_files_back(tmp_path):
    workspace = tmp_path / 'ws'
    seen = {}

    def hand_over(team):
        seen['context'] = team.tool_context

    async def answer(messages, tools=None, *, stream_cb=None):
        target = workspace / 'a.py'
        seen['context'].track_edit(target)
        target.write_text('written this turn\n', encoding='utf-8')
        return 'ok'

    team, ws = _rewind_team(tmp_path, answer, prepare=hand_over)
    assert (ws / 'a.py').exists()

    result = team.rewind(0, conversation=False)
    assert result['files'] == ['a.py']
    assert not (ws / 'a.py').exists()
    assert len(team.lead.messages) == 4


def test_rewinding_the_conversation_drops_the_later_turns(tmp_path):
    async def answer(messages, tools=None, *, stream_cb=None):
        return 'ok'

    team, _ws = _rewind_team(tmp_path, answer)
    assert len(team.lead.messages) == 4

    result = team.rewind(2, code=False)
    assert [msg.get('content') for msg in team.lead.messages] == ['first', 'ok']
    assert result['messages'] == 2


def test_the_history_can_count_what_each_file_gained_during_the_run(tmp_path):
    history = FileHistory(tmp_path / 'store', cwd=tmp_path)
    history.snapshot(0)
    kept = tmp_path / 'kept.py'
    kept.write_text('one\ntwo\n', encoding='utf-8')
    history.track_edit(kept)
    kept.write_text('one\nTWO\nthree\n', encoding='utf-8')
    history.track_edit(kept)
    fresh = tmp_path / 'fresh.py'
    history.track_edit(fresh)
    fresh.write_text('a\nb\n', encoding='utf-8')
    stats = history.session_stats()
    assert stats['kept.py']['deletions'] == 1
    assert stats['kept.py']['insertions'] == 2
    assert stats['fresh.py'] == {'insertions': 2, 'deletions': 0,
                                 'created': True}
