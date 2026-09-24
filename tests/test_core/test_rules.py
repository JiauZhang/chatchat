"""A rules directory holds markdown with a `paths:` frontmatter. Unconditional
ones join the standing instructions; the ones that name paths stay silent until
the model touches a file they cover, and then arrive once."""
import asyncio
from pathlib import Path

from chatchat.core.rules import RuleSet, matches, note
from chatchat.tool import Tool, ToolContext
from helpers import mock_team

LEAD = 'You are the lead.'


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _rule(directory: Path, name: str, paths: str = '',
          body: str = 'Use two spaces.\n') -> Path:
    frontmatter = f'paths: {paths}\n' if paths else ''
    return _write(directory / f'{name}.md',
                  f'---\n{frontmatter}---\n{body}' if frontmatter or paths
                  else body)


def _rules(tmp_path: Path, project: dict, user: dict = None):
    home = tmp_path / 'home'
    for name, spec in project.items():
        _rule(tmp_path / '.me' / 'rules', name, **spec)
    for name, spec in (user or {}).items():
        _rule(home / 'rules', name, **spec)
    return RuleSet.discover(cwd=tmp_path, home=home, subdir='.me')


def test_a_rule_is_offered_only_for_a_file_it_covers(tmp_path):
    rules = _rules(tmp_path, {'python': {'paths': 'src/**/*.py'}})
    assert [rule.path.name for rule in rules.relevant('src/app.py')] == \
        ['python.md']
    assert rules.relevant('README.md') == []


def test_a_rule_without_paths_is_eager_and_never_arrives_late(tmp_path):
    rules = _rules(tmp_path, {'general': {'paths': ''},
                              'scoped': {'paths': 'src/*.py'}})
    assert [rule.path.name for rule in rules.always()] == ['general.md']
    assert [rule.path.name for rule in rules.all()] == ['scoped.md']
    assert rules.relevant('src/app.py') != []


def test_paths_accept_a_comma_string_a_list_and_braces(tmp_path):
    home = tmp_path / 'home'
    _write(tmp_path / '.me' / 'rules' / 'one.md',
           '---\npaths: "a.py, b.py"\n---\nbody\n')
    _write(tmp_path / '.me' / 'rules' / 'two.md',
           '---\npaths:\n  - src/*.ts\n  - src/*.js\n---\nbody\n')
    _write(tmp_path / '.me' / 'rules' / 'three.md',
           '---\npaths: src/*.{ts,js}\n---\nbody\n')
    rules = RuleSet.discover(cwd=tmp_path, home=home, subdir='.me')
    assert sorted(r.path.name for r in rules.relevant('a.py')) == ['one.md']
    covered = sorted(r.path.name for r in rules.relevant('src/x.js'))
    assert covered == ['three.md', 'two.md']


def test_a_bare_name_matches_at_any_depth_but_a_slanted_one_is_anchored():
    assert matches('*.py', 'deep/inside/x.py')
    assert matches('src/*.py', 'src/app.py')
    assert not matches('src/*.py', 'src/web/app.py')
    assert not matches('src/*.py', 'web/src/app.py')


def test_a_double_star_crosses_directories_and_a_star_does_not():
    assert matches('src/**/*.py', 'src/a/b/c.py')
    assert not matches('src/*.py', 'src/a/b.py')
    assert matches('**/legacy/*.py', 'x/y/legacy/a.py')


def test_a_directory_and_its_trailing_double_star_are_the_same(tmp_path):
    assert matches('docs/', 'docs/a/b.md')
    assert matches('docs/**', 'docs/a/b.md')
    assert not matches('docs/**', 'notes/a.md')


def test_rules_are_found_in_subdirectories_and_only_markdown_counts(tmp_path):
    home = tmp_path / 'home'
    _rule(tmp_path / '.me' / 'rules' / 'deep' / 'nest', 'own',
          paths='src/**')
    _write(tmp_path / '.me' / 'rules' / 'ignored.txt', 'paths: src\n')
    rules = RuleSet.discover(cwd=tmp_path, home=home, subdir='.me')
    assert [rule.path.name for rule in rules.all()] == ['own.md']


def test_a_file_outside_the_anchors_reaches_no_rule(tmp_path):
    rules = _rules(tmp_path, {'python': {'paths': '**/*.py'}})
    assert rules.relevant(str(tmp_path.parent / 'elsewhere.py')) == []


def test_a_user_rule_is_anchored_at_the_working_directory(tmp_path):
    rules = _rules(tmp_path, {}, {'python': {'paths': 'src/*.py'}})
    assert [rule.scope for rule in rules.relevant('src/app.py')] == ['user']


def test_each_rule_arrives_once_until_the_set_is_reset(tmp_path):
    rules = _rules(tmp_path, {'python': {'paths': 'src/*.py'}})
    assert len(rules.relevant('src/a.py')) == 1
    assert rules.relevant('src/b.py') == []
    rules.reset()
    assert len(rules.relevant('src/a.py')) == 1


def test_the_note_names_the_rule_and_the_file_that_pulled_it_in(tmp_path):
    rules = _rules(tmp_path, {'python': {'paths': 'src/*.py',
                                         'body': 'Use two spaces.\n'}})
    text = note(rules.relevant('src/a.py'), 'src/a.py')
    assert 'src/a.py' in text and 'Use two spaces.' in text
    assert 'paths: src/*.py' not in text


def _reader(returns=''):
    def read(context, file_path: str = ''):
        return returns if returns else f'contents of {file_path}'

    return Tool(tool=read, name='Read', description='read a file',
                read_only=True, get_path=lambda i: i.get('file_path', ''))


def _run(tmp_path, tool, file_path, twice=False):
    rules = _rules(tmp_path, {'python': {'paths': 'src/*.py',
                                         'body': 'Use two spaces.\n'}})

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: 'ok',
                         lead_instruction=LEAD, tools=[tool], rules=rules,
                         tool_context=ToolContext(cwd=Path(tmp_path)))
        out = await team.execute_tool('Read', {'file_path': file_path},
                                      team.lead, 't1')
        again = (await team.execute_tool('Read', {'file_path': file_path},
                                         team.lead, 't2')) if twice else None
        return team, out, again

    return asyncio.run(main())


def test_compaction_rearms_the_rules_so_they_arrive_again(tmp_path):
    rules = _rules(tmp_path, {'python': {'paths': 'src/*.py'}})

    async def main():
        team = mock_team('demo', lambda m, t=None, stream_cb=None: 'ok',
                         lead_instruction=LEAD, rules=rules,
                         tool_context=ToolContext(cwd=Path(tmp_path)))
        chat = ([{'role': 'user', 'content': f'question {n}'}
                 for n in range(14)])
        assert rules.relevant('src/a.py') != []
        await team.maybe_compact(chat, force=True)
        return rules.relevant('src/a.py')

    assert asyncio.run(main()) != []


def test_reading_a_file_brings_in_the_rule_that_covers_it(tmp_path):
    _, out, _ = _run(tmp_path, _reader(), 'src/a.py')
    assert 'Use two spaces.' in out.additional_context


def test_reading_a_file_outside_every_rule_adds_nothing(tmp_path):
    _, out, _ = _run(tmp_path, _reader(), 'notes/a.md')
    assert out.additional_context == ''


def test_a_rule_is_not_repeated_for_the_next_file(tmp_path):
    _, out, again = _run(tmp_path, _reader(), 'src/a.py', twice=True)
    assert 'Use two spaces.' in out.additional_context
    assert 'Use two spaces.' not in again.additional_context


def test_a_failed_read_does_not_bring_in_a_rule(tmp_path):
    _, out, _ = _run(tmp_path, _reader('Error: file does not exist'),
                     'src/a.py')
    assert 'Use two spaces.' not in out.additional_context


def test_editing_a_file_does_not_bring_in_its_rule(tmp_path):
    def edit(context, file_path: str = ''):
        return 'ok'

    writer = Tool(tool=edit, name='Edit', description='edit a file',
                  get_path=lambda i: i.get('file_path', ''))
    _, out, _ = _run(tmp_path, writer, 'src/a.py')
    assert 'Use two spaces.' not in out.additional_context
