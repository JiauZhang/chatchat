"""Skills are discovered as markdown with a frontmatter block, and the body is
only read when the skill is used, so the listing has to fit a budget."""
from chatchat.knowledge.skills import SkillRegistry


def _skill(root, name, frontmatter, body='do the thing\n'):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / 'SKILL.md').write_text(
        f'---\n{frontmatter}\n---\n{body}', encoding='utf-8')
    return directory


def _pair(tmp_path, user, project):
    home = tmp_path / 'home' / 'skills'
    workspace = tmp_path / 'ws'
    for name, text in user.items():
        _skill(home, name, text)
    for name, text in project.items():
        _skill(workspace / '.me' / 'skills', name, text)
    return SkillRegistry.discover(cwd=workspace, home=home.parent,
                                  subdir='.me')


def test_a_project_skill_replaces_the_user_skill_of_the_same_name(tmp_path):
    registry = _pair(tmp_path,
                     {'notes': 'name: notes\ndescription: from the user\n'},
                     {'notes': 'name: notes\ndescription: from the project\n'})
    skill = registry.get('notes')
    assert skill.description == 'from the project'
    assert skill.source == 'project'
    assert [other.name for other in registry.all()] == ['notes']


def test_the_directory_names_a_skill_that_omits_its_own(tmp_path):
    registry = _pair(tmp_path, {'notes': 'description: from the user\n'}, {})
    assert [skill.name for skill in registry.all()] == ['notes']


def test_a_skill_without_a_description_is_skipped_and_reported(tmp_path):
    registry = _pair(tmp_path, {'vague': 'name: vague\n'},
                     {'useful': 'name: useful\ndescription: d\n'})
    assert [skill.name for skill in registry.all()] == ['useful']
    assert any('vague' in problem for problem in registry.problems)


def test_the_body_is_read_when_the_skill_is_used_and_args_are_filled_in(
        tmp_path):
    home = tmp_path / 'home' / 'skills'
    _skill(home, 'commit', 'name: commit\ndescription: write a message\n',
           'Summarise what changed for $ARGUMENTS.\n')
    _skill(home, 'plain', 'name: plain\ndescription: d\n', 'Read the code.\n')
    registry = SkillRegistry.discover(cwd=tmp_path / 'ws',
                                      home=tmp_path / 'home', subdir='skills')
    assert registry.get('commit').render('the parser') == \
        'Summarise what changed for the parser.\n'
    assert registry.get('plain').render('the parser') == \
        'Read the code.\n\nArgs: the parser\n'


def test_the_listing_fits_the_budget_by_shrinking_descriptions(tmp_path):
    registry = _pair(tmp_path,
                     {f's{i}': f'name: s{i}\ndescription: '
                               f'{"x" * 120}\n' for i in range(6)},
                     {})
    wide = registry.listing(budget=4000)
    assert wide.count('\n') == 5
    assert 'x' * 120 in wide
    tight = registry.listing(budget=200)
    assert len(tight) <= 200
    assert all(f'- s{i}:' in tight for i in range(6))


def test_a_long_when_to_use_shares_the_entry_but_is_capped(tmp_path):
    registry = _pair(tmp_path,
                     {'big': 'name: big\ndescription: short\n'
                             'when_to_use: ' + 'y' * 600 + '\n'},
                     {})
    line = registry.listing(budget=4000)
    assert 'short - ' in line
    assert 'y' * 251 not in line


def test_allowed_tools_accept_a_list_and_a_comma_string(tmp_path):
    registry = _pair(tmp_path,
                     {'csv': 'name: csv\ndescription: d\nallowed-tools: '
                             'Read, Grep\n',
                      'seq': 'name: seq\ndescription: d\nallowed-tools:\n'
                             '  - Read\n  - Bash\n'},
                     {})
    assert registry.get('csv').allowed_tools == ('Read', 'Grep')
    assert registry.get('seq').allowed_tools == ('Read', 'Bash')


def test_path_globs_are_kept_for_conditionally_relevant_skills(tmp_path):
    registry = _pair(tmp_path,
                     {'tests': 'name: tests\ndescription: d\n'
                               'paths: tests/**, *_test.py\n'},
                     {})
    skill = registry.get('tests')
    assert skill.matches('tests/test_core/test_skills.py') is True
    assert skill.matches('README.md') is False


def test_a_directory_without_a_skill_file_is_ignored(tmp_path):
    home = tmp_path / 'home' / 'skills'
    (home / 'empty').mkdir(parents=True)
    _skill(home, 'real', 'name: real\ndescription: d\n')
    registry = SkillRegistry.discover(cwd=tmp_path / 'ws',
                                      home=tmp_path / 'home', subdir='skills')
    assert [skill.name for skill in registry.all()] == ['real']


def test_a_broken_frontmatter_block_is_reported_not_raised(tmp_path):
    home = tmp_path / 'home' / 'skills'
    directory = _skill(home, 'broken', 'name: broken\ndescription: d\n')
    (directory / 'SKILL.md').write_text('---\nname: [unclosed\n---\nbody\n',
                                        encoding='utf-8')
    registry = SkillRegistry.discover(cwd=tmp_path / 'ws',
                                      home=tmp_path / 'home', subdir='skills')
    assert registry.all() == []
    assert any('broken' in problem for problem in registry.problems)


def _registry(tmp_path, name='notes', body='Read the notes and summarise.\n'):
    home = tmp_path / 'home' / 'skills'
    _skill(home, name, f'name: {name}\ndescription: work on {name}\n', body)
    return SkillRegistry.discover(cwd=tmp_path / 'ws', home=tmp_path / 'home',
                                  subdir='skills')


def test_a_team_without_skills_does_not_offer_the_tool(tmp_path):
    import asyncio

    from helpers import mock_team

    async def main():
        team = mock_team('noskill')
        return [schema['name'] for schema in
                team.tool_schemas(team.tool_context)]

    assert 'Skill' not in asyncio.run(main())


def test_the_skill_tool_description_lists_what_is_available(tmp_path):
    import asyncio

    from helpers import mock_team

    async def main():
        team = mock_team('listed', skills=_registry(tmp_path))
        schema = next(schema for schema in team.tool_schemas(team.tool_context)
                      if schema['name'] == 'Skill')
        return schema['description']

    description = asyncio.run(main())
    assert '- notes: work on notes' in description


def test_using_a_skill_gives_the_model_its_full_body(tmp_path):
    import asyncio

    from helpers import mock_team

    async def main():
        team = mock_team('used', skills=_registry(tmp_path))
        return await team.execute_tool(
            'Skill', {'skill': 'notes', 'args': 'the second one'},
            team.lead)

    outcome = asyncio.run(main())
    assert outcome.text.startswith('Read the notes and summarise.')
    assert 'Args: the second one' in outcome.text


def test_an_unknown_skill_names_the_ones_that_exist(tmp_path):
    import asyncio

    from helpers import mock_team

    async def main():
        team = mock_team('missing', skills=_registry(tmp_path))
        return await team.execute_tool('Skill', {'skill': 'nope'},
                                       team.lead)

    outcome = asyncio.run(main())
    assert 'no such skill: nope' in outcome.text
    assert 'notes' in outcome.text


def test_extra_roots_can_be_loaded_and_the_first_one_wins(tmp_path):
    extra = tmp_path / 'plugin' / 'skills'
    _skill(extra, 'notes', 'name: notes\ndescription: from the plugin\n')
    home = tmp_path / 'home' / 'skills'
    _skill(home, 'notes', 'name: notes\ndescription: from the user\n')
    registry = SkillRegistry.load([(extra, 'plugin'), (home, 'user')])
    assert registry.get('notes').description == 'from the plugin'
    assert registry.get('notes').source == 'plugin'
