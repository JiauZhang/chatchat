"""Skills are discovered as markdown with a frontmatter block, and the body is
only read when the skill is used, so the listing has to fit a budget."""

from chatchat.runtime.agent import is_attachment_message
from chatchat.runtime.skills import SkillRegistry
from chatchat.runtime.skills import Skill
import asyncio
from helpers import RecordingProduct, mock_team
from chatchat.tools.builtin import skills as _skills
from chatchat.client import MockClient, ToolUse
from chatchat.team.team import Team
from chatchat.tool import Tool


def _skill(root, name, frontmatter, body="do the thing\n"):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return directory


def _pair(tmp_path, user, project):
    home = tmp_path / "home" / "skills"
    workspace = tmp_path / "ws"
    for name, text in user.items():
        _skill(home, name, text)
    for name, text in project.items():
        _skill(workspace / ".me" / "skills", name, text)
    return SkillRegistry.discover(cwd=workspace, home=home.parent, subdir=".me")


def test_a_project_skill_replaces_the_user_skill_of_the_same_name(tmp_path):
    registry = _pair(
        tmp_path,
        {"notes": "name: notes\ndescription: from the user\n"},
        {"notes": "name: notes\ndescription: from the project\n"},
    )
    skill = registry.get("notes")
    assert skill.description == "from the project"
    assert skill.source == "project"
    assert [other.name for other in registry.all()] == ["notes"]


def test_the_directory_names_a_skill_that_omits_its_own(tmp_path):
    registry = _pair(tmp_path, {"notes": "description: from the user\n"}, {})
    assert [skill.name for skill in registry.all()] == ["notes"]


def test_a_skill_without_a_description_is_skipped_and_reported(tmp_path):
    registry = _pair(tmp_path, {"vague": "name: vague\n"}, {"useful": "name: useful\ndescription: d\n"})
    assert [skill.name for skill in registry.all()] == ["useful"]
    assert any("vague" in problem for problem in registry.problems)


def test_the_body_is_read_when_the_skill_is_used_and_args_are_filled_in(tmp_path):
    home = tmp_path / "home" / "skills"
    _skill(home, "commit", "name: commit\ndescription: write a message\n", "Summarise what changed for $ARGUMENTS.\n")
    _skill(home, "plain", "name: plain\ndescription: d\n", "Read the code.\n")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    assert registry.get("commit").render("the parser") == "Summarise what changed for the parser.\n"
    assert registry.get("plain").render("the parser") == "Read the code.\n\nArgs: the parser\n"


def test_the_listing_fits_the_budget_by_shrinking_descriptions(tmp_path):
    registry = _pair(tmp_path, {f"s{i}": f"name: s{i}\ndescription: {'x' * 120}\n" for i in range(6)}, {})
    wide = registry.listing(budget=4000)
    assert wide.count("\n") == 5
    assert "x" * 120 in wide
    tight = registry.listing(budget=200)
    assert len(tight) <= 200
    assert all(f"- s{i}:" in tight for i in range(6))


def test_a_long_when_to_use_shares_the_entry_but_is_capped(tmp_path):
    registry = _pair(tmp_path, {"big": "name: big\ndescription: short\nwhen_to_use: " + "y" * 600 + "\n"}, {})
    line = registry.listing(budget=4000)
    assert "short - " in line
    assert "y" * 251 not in line


def test_allowed_tools_accept_a_list_and_a_comma_string(tmp_path):
    registry = _pair(
        tmp_path,
        {
            "csv": "name: csv\ndescription: d\nallowed-tools: Read, Grep\n",
            "seq": "name: seq\ndescription: d\nallowed-tools:\n  - Read\n  - Bash\n",
        },
        {},
    )
    assert registry.get("csv").allowed_tools == ("Read", "Grep")
    assert registry.get("seq").allowed_tools == ("Read", "Bash")


def test_path_globs_are_kept_for_conditionally_relevant_skills(tmp_path):
    registry = _pair(tmp_path, {"tests": "name: tests\ndescription: d\npaths: tests/**, *_test.py\n"}, {})
    skill = registry.get("tests")
    assert skill.matches("tests/test_core/test_skills.py") is True
    assert skill.matches("README.md") is False


def test_a_directory_without_a_skill_file_is_ignored(tmp_path):
    home = tmp_path / "home" / "skills"
    (home / "empty").mkdir(parents=True)
    _skill(home, "real", "name: real\ndescription: d\n")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    assert [skill.name for skill in registry.all()] == ["real"]


def test_a_broken_frontmatter_block_is_reported_not_raised(tmp_path):
    home = tmp_path / "home" / "skills"
    directory = _skill(home, "broken", "name: broken\ndescription: d\n")
    (directory / "SKILL.md").write_text('---\nname: "unclosed quote\n---\nbody\n', encoding="utf-8")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    assert registry.all() == []
    assert any("broken" in problem for problem in registry.problems)


def test_the_invocation_flags_come_from_the_frontmatter(tmp_path):
    registry = _pair(
        tmp_path,
        {
            "askable": "name: askable\ndescription: d\nargument-hint: [what went wrong]\ndisable-model-invocation: true\n",
            "bracketed": 'name: bracketed\ndescription: d\nargument-hint: "[file]"\n',
            "quiet": "name: quiet\ndescription: d\nuser-invocable: false\n",
        },
        {},
    )
    askable = registry.get("askable")
    assert (askable.argument_hint, askable.disable_model_invocation, askable.user_invocable) == ("what went wrong", True, True)
    assert registry.get("bracketed").argument_hint == "[file]"
    assert registry.get("quiet").user_invocable is False
    assert registry.get("quiet").disable_model_invocation is False


def test_a_skill_the_model_may_not_call_is_left_out_of_its_listing(tmp_path):
    registry = _pair(
        tmp_path,
        {
            "hidden": "name: hidden\ndescription: for the user only\ndisable-model-invocation: true\n",
            "shown": "name: shown\ndescription: for anyone\n",
        },
        {},
    )
    assert [skill.name for skill in registry.for_model()] == ["shown"]
    assert "hidden" not in registry.listing(4000)
    assert "hidden" in [skill.name for skill in registry.all()]


def test_a_registered_skill_is_used_like_a_directory_one(tmp_path):

    registry = _pair(tmp_path, {}, {})
    registry.register(
        Skill(name="built", description="d", source="builtin", body_text="Say what the log shows for $ARGUMENTS.")
    )
    assert registry.get("built").render("the crash") == "Say what the log shows for the crash."
    assert registry.get("built").source == "builtin"


def test_a_registered_skill_builds_its_prompt_as_it_is_called(tmp_path):

    seen = []
    registry = _pair(tmp_path, {}, {})
    registry.register(
        Skill(
            name="live",
            description="d",
            source="builtin",
            builder=lambda args: seen.append(args) or f"seen {len(seen)}: {args}",
        )
    )
    assert registry.get("live").render("the crash") == "seen 1: the crash"
    assert registry.get("live").render("again") == "seen 2: again"


def _registry(tmp_path, name="notes", body="Read the notes and summarise.\n"):
    home = tmp_path / "home" / "skills"
    _skill(home, name, f"name: {name}\ndescription: work on {name}\n", body)
    return SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")


def test_a_team_without_skills_does_not_offer_the_tool(tmp_path):

    async def main():
        team = mock_team("noskill")
        return [schema["name"] for schema in team.tool_schemas(team.tool_context)]

    assert "Skill" not in asyncio.run(main())


def test_the_skill_tool_description_is_static_the_listing_rides_an_attachment(tmp_path):

    async def main():
        team = mock_team("listed", skills=_registry(tmp_path))
        schema = next(schema for schema in team.tool_schemas(team.tool_context) if schema["name"] == "Skill")
        return schema["description"]

    description = asyncio.run(main())
    assert "system-reminder" in description
    assert "- notes:" not in description


def test_using_a_skill_gives_the_model_its_full_body(tmp_path):

    async def main():
        team = mock_team("used", skills=_registry(tmp_path))
        return await team.execute_tool("Skill", {"skill": "notes", "args": "the second one"}, team.lead)

    outcome = asyncio.run(main())
    assert outcome.text.startswith("Read the notes and summarise.")
    assert "Args: the second one" in outcome.text


def test_an_unknown_skill_names_the_ones_that_exist(tmp_path):

    async def main():
        team = mock_team("missing", skills=_registry(tmp_path))
        return await team.execute_tool("Skill", {"skill": "nope"}, team.lead)

    outcome = asyncio.run(main())
    assert "no such skill: nope" in outcome.text
    assert "notes" in outcome.text


def test_extra_roots_can_be_loaded_and_the_first_one_wins(tmp_path):
    extra = tmp_path / "plugin" / "skills"
    _skill(extra, "notes", "name: notes\ndescription: from the plugin\n")
    home = tmp_path / "home" / "skills"
    _skill(home, "notes", "name: notes\ndescription: from the user\n")
    registry = SkillRegistry.load([(extra, "plugin"), (home, "user")])
    assert registry.get("notes").description == "from the plugin"
    assert registry.get("notes").source == "plugin"


def test_using_a_skill_tells_the_host_what_it_declared_it_needs(tmp_path):

    recorded = []

    async def main():
        team = mock_team("granting")
        recorded.append(team.attach(RecordingProduct()))
        registry = team.skills
        registry.register(Skill(name="notes", description="d", body_text="write them", allowed_tools=("Read", "Grep")))
        registry.register(Skill(name="plain", description="d", body_text="read them"))
        await _skills.use_skill(None, team=team, agent=team.lead, input={"skill": "notes"})
        await _skills.use_skill(None, team=team, agent=team.lead, input={"skill": "plain"})

    asyncio.run(main())
    assert recorded[0].granted == [("Read", "Grep")]


def test_a_conditional_skill_hides_from_the_model_until_a_path_activates_it(tmp_path):
    home = tmp_path / "home" / "skills"
    _skill(home, "tester", "name: tester\ndescription: the testing rules\npaths: test_*.py\n")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    version = registry.listing_version

    assert [skill.name for skill in registry.for_model()] == []
    assert [skill.name for skill in registry.for_user()] == ["tester"]

    fresh = registry.activate_for_paths([str(tmp_path / "ws" / "test_x.py")])
    assert [skill.name for skill in fresh] == ["tester"]
    assert [skill.name for skill in registry.for_model()] == ["tester"]
    assert registry.listing_version > version
    assert registry.activate_for_paths([str(tmp_path / "ws" / "test_x.py")]) == []


def test_a_non_matching_path_leaves_the_conditional_skill_hidden(tmp_path):
    home = tmp_path / "home" / "skills"
    _skill(home, "tester", "name: tester\ndescription: the testing rules\npaths: test_*.py\n")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    assert registry.activate_for_paths([str(tmp_path / "ws" / "src" / "main.py")]) == []
    assert registry.for_model() == []


def test_touching_a_matching_file_lists_the_skill_in_a_system_reminder(tmp_path):

    home = tmp_path / "home" / "skills"
    _skill(home, "tester", "name: tester\ndescription: the testing rules\npaths: test_*.py\n")
    registry = SkillRegistry.discover(cwd=tmp_path / "ws", home=tmp_path / "home", subdir="skills")
    touched = tmp_path / "ws" / "test_x.py"
    touched.parent.mkdir(parents=True)
    touched.write_text("x", encoding="utf-8")

    async def handler(messages, tools=None, *, stream_cb=None):
        if any(isinstance(m.get("content"), list) for m in messages):
            return "done"
        return [ToolUse("Read", {"file_path": str(touched)}, "t1")]

    def read(context, file_path):
        return "content"

    async def main():
        team = Team(
            "cond",
            MockClient(handler=handler),
            skills=registry,
            tools=[
                Tool(tool=read, name="Read", description="read a file", read_only=True, get_path=lambda a: a.get("file_path"))
            ],
        )
        await team.conversation.query("look at the test file")
        return team

    team = asyncio.run(main())

    assert registry.activated == {"tester"}
    reminders = [
        m["content"]
        for m in team.lead.messages
        if m["role"] == "user" and isinstance(m["content"], str) and "Available skills:" in m["content"]
    ]
    assert any("- tester: the testing rules" in reminder for reminder in reminders)


def test_the_skill_listing_rides_a_marked_attachment_message(tmp_path):

    async def main():
        team = mock_team("listed", skills=_registry(tmp_path), handler=lambda messages, tools=None: "ok")
        await team.conversation.query("hi")
        return team.conversation.transcript()

    transcript = asyncio.run(main())
    listing = [m for m in transcript if m.get("attachment")]
    assert len(listing) == 1
    assert listing[0]["role"] == "user"
    assert "<system-reminder>" in listing[0]["content"]
    assert "- notes:" in listing[0]["content"]


def test_is_attachment_message_judges_only_marked_user_messages():
    assert is_attachment_message({"role": "user", "content": "hi"}) is False
    assert is_attachment_message({"role": "assistant", "content": "hi"}) is False
    assert is_attachment_message({"role": "user", "content": [{"type": "tool_result"}]}) is False
    assert (
        is_attachment_message({"role": "user", "content": "<system-reminder>x</system-reminder>", "attachment": True}) is True
    )
    assert is_attachment_message(None) is False
