"""Worktrees are only useful if a session really moves into one, so every test
here runs against a real git repository."""
import asyncio
import subprocess

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


def test_the_worktree_tools_are_offered_only_where_git_is(tmp_path):
    root = _repo(tmp_path)
    plain = tmp_path / 'plain'
    plain.mkdir()

    async def main():
        in_repo = _team(root)
        elsewhere = _team(plain)
        names = lambda team: [schema['name'] for schema in
                              team.tool_schemas(team.tool_context)]
        return names(in_repo), names(elsewhere)

    in_repo, elsewhere = _run(main())
    assert {'enter_worktree', 'exit_worktree'} <= set(in_repo)
    assert 'enter_worktree' not in elsewhere
