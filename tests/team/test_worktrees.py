"""Worktrees are only useful if a session really moves into one, so every test
here runs against a real git repository."""
import asyncio
import os
import re
import subprocess
from pathlib import Path

import pytest
from chatchat.tool import ToolContext
from helpers import mock_team

git = pytest.importorskip('shutil').which('git')


def _repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run([git, 'init', '-q'], cwd=root, check=True)
    subprocess.run([git, 'config', 'user.email', 'test@example.com'],
                   cwd=root, check=True)
    subprocess.run([git, 'config', 'user.name', 'test'], cwd=root, check=True)
    (root / 'a.txt').write_text('committed\n', encoding='utf-8')
    subprocess.run([git, 'add', 'a.txt'], cwd=root, check=True)
    subprocess.run([git, 'commit', '-qm', 'first'], cwd=root, check=True)
    return root


def _team(root, **kw):
    return mock_team('wt', tool_context=ToolContext(cwd=root), **kw)


def _run(coro):
    return asyncio.run(coro)


def test_a_session_can_move_into_a_fresh_worktree(tmp_path):
    root = _repo(tmp_path)
    seen = []

    async def main():
        team = _team(root)
        team.hooks.register('CwdChanged', '*',
                            fn=lambda inp: seen.append(inp['cwd']) or True)
        await team.enter_worktree('experiment')
        (team.tool_context.cwd / 'b.txt').write_text('only there\n',
                                                    encoding='utf-8')
        return team

    team = _run(main())
    assert team.worktree['name'] == 'experiment'
    assert team.tool_context.cwd != root
    assert (root / 'b.txt').exists() is False
    assert (team.tool_context.cwd / 'a.txt').exists()
    assert seen and str(root) in str(seen[0])


def test_two_worktrees_cannot_be_entered_at_once(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('one')
        error = ''
        try:
            await team.enter_worktree('two')
        except ValueError as exc:
            error = str(exc)
        return team, error

    team, error = _run(main())
    assert 'already' in error and team.worktree['name'] == 'one'


def test_leaving_can_keep_or_destroy_the_worktree(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('kept')
        kept = team.tool_context.cwd
        await team.exit_worktree(keep=True)
        team2 = _team(root)
        await team2.enter_worktree('gone')
        removed = team2.tool_context.cwd
        await team2.exit_worktree()
        return kept, removed, team.tool_context.cwd, team2.worktree

    kept, removed, back, worktree = _run(main())
    assert kept.is_dir()
    assert not removed.exists()
    assert back == root
    assert worktree is None


def test_a_directory_without_git_refuses(tmp_path):
    plain = tmp_path / 'plain'
    plain.mkdir()

    async def main():
        return await _team(plain).enter_worktree('nope')

    message = _run(main())
    assert message.startswith('Error:') and 'git' in message


def test_the_worktree_tools_are_offered_only_where_the_work_can_be_isolated(
        tmp_path):
    root = _repo(tmp_path)
    plain = tmp_path / 'plain'
    plain.mkdir()

    async def main():
        in_repo = _team(root)
        elsewhere = _team(plain)
        names = lambda team: [schema['name'] for schema in
                              team.tool_schemas(team.tool_context)]
        without = names(elsewhere)
        elsewhere.hooks.register('WorktreeCreate', '*', fn=lambda inp: 'x')
        return names(in_repo), without, names(elsewhere)

    in_repo, without, with_hook = _run(main())
    assert {'EnterWorktree', 'ExitWorktree'} <= set(in_repo)
    assert 'EnterWorktree' not in without
    assert 'EnterWorktree' in with_hook


def test_a_worktree_without_a_name_gets_a_readable_one(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree()
        first = (team.worktree['name'], team.tool_context.cwd)
        await team.exit_worktree(keep=True)
        again = _team(root)
        await again.enter_worktree()
        return first, (again.worktree['name'], again.tool_context.cwd)

    (name, path), (second_name, second_path) = _run(main())
    assert re.fullmatch(r'[a-z]+-[a-z]+-[a-z]+', name)
    assert (second_name, second_path) == (name, path)


def test_a_name_that_could_escape_the_worktrees_directory_is_refused(tmp_path):
    root = _repo(tmp_path)

    async def one(name):
        return await _team(root).enter_worktree(name)

    for name in ('../elsewhere', 'a b', '.', '..', 'x' * 65, '/abs', 'a//b'):
        assert _run(one(name)).startswith('Error:'), name
    assert not (root / '.pyclaw').exists()


def test_a_nested_name_is_flattened_into_one_branch_and_directory(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('asm/feature')
        return team

    team = _run(main())
    assert team.tool_context.cwd == root / '.pyclaw' / 'worktrees' / 'asm+feature'
    assert team.worktree['branch'] == 'worktree-asm+feature'
    listed = subprocess.run([git, 'branch', '--list'], cwd=root,
                            capture_output=True, text=True).stdout
    assert 'worktree-asm+feature' in listed


def test_the_record_says_which_branch_the_work_left_behind(tmp_path):
    root = _repo(tmp_path)
    branch = subprocess.run([git, 'rev-parse', '--abbrev-ref', 'HEAD'],
                            cwd=root, capture_output=True,
                            text=True).stdout.strip()

    async def main():
        team = _team(root)
        await team.enter_worktree('trip')
        return team

    record = _run(main()).worktree
    assert record['origin_branch'] == branch
    assert re.fullmatch(r'[0-9a-f]{40}', record['origin_head'])


def test_an_untouched_worktree_is_removed_without_a_fuss(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('clean')
        return await team.exit_worktree()

    message = _run(main())
    assert 'removed' in message and 'Discarded' not in message
    assert not (root / '.pyclaw' / 'worktrees' / 'clean').exists()


def test_work_that_lives_only_in_the_worktree_is_not_thrown_away(tmp_path):
    root = _repo(tmp_path)

    async def enter(team):
        await team.enter_worktree('careful')
        (team.tool_context.cwd / 'new.txt').write_text('work\n', encoding='utf-8')

    async def refused():
        team = _team(root)
        await enter(team)
        message = await team.exit_worktree()
        return message, team.tool_context.cwd, team.worktree

    message, cwd, record = _run(refused())
    assert message.startswith('Error:') and '1 uncommitted file' in message
    assert cwd == record['path'] and record is not None

    async def discarded():
        team = _team(root)
        team.worktree = record
        team.set_cwd(cwd)
        message = await team.exit_worktree(discard=True)
        return message, cwd

    message, path = _run(discarded())
    assert 'Discarded 1 uncommitted file' in message
    assert not path.exists()


def test_commits_made_only_on_the_worktree_branch_count_as_work(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('committed')
        workdir = team.tool_context.cwd
        (workdir / 'b.txt').write_text('work\n', encoding='utf-8')
        subprocess.run([git, 'add', 'b.txt'], cwd=workdir, check=True)
        subprocess.run([git, 'commit', '-qm', 'work'], cwd=workdir, check=True)
        refused = await team.exit_worktree()
        return refused, team

    refused, team = _run(main())
    assert refused.startswith('Error:') and '1 commit' in refused
    done = _run(team.exit_worktree(discard=True))
    assert 'Discarded 1 commit' in done


def test_a_worktree_that_is_still_there_is_entered_again(tmp_path):
    root = _repo(tmp_path)

    async def main():
        team = _team(root)
        await team.enter_worktree('again')
        path = team.tool_context.cwd
        (path / 'keep.txt').write_text('still here\n', encoding='utf-8')
        await team.exit_worktree(keep=True)
        later = _team(root)
        message = await later.enter_worktree('again')
        return path, later, message

    path, later, message = _run(main())
    assert later.tool_context.cwd == path
    assert (later.tool_context.cwd / 'keep.txt').exists()
    assert 'again' in message


def test_a_hook_can_isolate_the_work_where_there_is_no_git(tmp_path):
    plain = tmp_path / 'plain'
    plain.mkdir()
    elsewhere = tmp_path / 'isolated'

    async def main():
        team = _team(plain)
        seen = []
        team.hooks.register('WorktreeCreate', '*',
                            fn=lambda inp: seen.append(dict(inp))
                            or str(elsewhere))
        message = await team.enter_worktree('by-hook')
        removed = []
        team.hooks.register('WorktreeRemove', '*',
                            fn=lambda inp: removed.append(dict(inp)) or True)
        refused = await team.exit_worktree()
        gone = await team.exit_worktree(discard=True)
        return message, seen, removed, refused, gone, team

    message, created, removed, refused, gone, team = _run(main())
    assert str(elsewhere) in message and team.worktree is None
    assert created[0]['name'] == 'by-hook'
    assert refused.startswith('Error:') and 'could not say' in refused
    assert removed[0]['worktree_path'] == str(elsewhere)
    assert 'Back at' in gone


def test_the_process_directory_moves_with_the_session_and_comes_back(tmp_path):
    root = _repo(tmp_path)
    before = Path(os.getcwd())

    async def main():
        team = _team(root)
        team._cwd_changed = os.chdir
        await team.enter_worktree('inside')
        inside = Path(os.getcwd())
        await team.exit_worktree(keep=True)
        return inside, Path(os.getcwd())

    inside, after = _run(main())
    assert inside == root / '.pyclaw' / 'worktrees' / 'inside'
    assert after == root
    os.chdir(before)
