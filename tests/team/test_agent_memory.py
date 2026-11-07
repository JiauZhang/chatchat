"""An agent type can keep its own notes between runs, in one of three places."""

import asyncio
from pathlib import Path

from chatchat.runtime.agent_memory import AgentMemory
from helpers import mock_team


def _memory(tmp_path):
    return AgentMemory(
        roots={
            "user": tmp_path / "home" / "agent-memory",
            "project": tmp_path / "ws" / ".pyclaw" / "agent-memory",
            "local": tmp_path / "ws" / ".pyclaw" / "agent-memory-local",
        }
    )


def _write(directory, text):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "MEMORY.md").write_text(text, encoding="utf-8")


def test_each_scope_has_its_own_directory_for_one_agent_type(tmp_path):
    memory = _memory(tmp_path)
    assert memory.directory("reviewer", "user").name == "reviewer"
    assert memory.directory("reviewer", "user").parent == (tmp_path / "home" / "agent-memory")
    assert memory.directory("reviewer", "project") != (memory.directory("reviewer", "local"))
    assert memory.directory("a:b", "user").name == "a-b"


def test_the_prompt_carries_what_was_stored_and_where_it_lives(tmp_path):
    memory = _memory(tmp_path)
    _write(memory.directory("reviewer", "project"), "## MEMORY.md\n\n- this repo lints with ruff\n")
    text = memory.prompt("reviewer", "project")
    assert "this repo lints with ruff" in text
    assert str(memory.directory("reviewer", "project")) in text
    assert memory.directory("reviewer", "project").is_dir()


def test_an_agent_without_notes_is_told_there_are_none_yet(tmp_path):
    memory = _memory(tmp_path)
    text = memory.prompt("reviewer", "user")
    assert "empty" in text


def test_a_long_entrypoint_is_cut_at_the_line_cap(tmp_path):
    memory = _memory(tmp_path)
    _write(memory.directory("reviewer", "user"), "\n".join(f"line {index}" for index in range(400)))
    text = memory.prompt("reviewer", "user")
    assert "line 199" in text
    assert "line 200" not in text


def test_writing_into_any_memory_root_needs_no_approval(tmp_path):
    memory = _memory(tmp_path)
    inside = memory.directory("reviewer", "project") / "notes.md"
    assert memory.contains(Path(inside)) is True
    assert memory.contains(tmp_path / "ws" / "app.py") is False


def _spawned(team, agent_type):
    return team.roster.agents[
        next(iter(agent_id for agent_id in team.roster.agents if agent_id != team.lead.agent_id))
    ].instruction


def test_an_agent_with_a_memory_scope_starts_with_its_notes(tmp_path):

    async def main():
        team = mock_team("mem1")
        team.agent_memory = _memory(tmp_path)
        team.agent_memory.directory("reviewer", "project").mkdir(parents=True, exist_ok=True)
        (team.agent_memory.directory("reviewer", "project") / "MEMORY.md").write_text("- prefer pytest", encoding="utf-8")
        team.agent_defs.define("reviewer", system_prompt="review it", metadata={"memory": "project"})
        await team.spawn_subagent("look at this", subagent_type="reviewer")
        return _spawned(team, "reviewer")

    instruction = asyncio.run(main())
    assert "prefer pytest" in instruction
    assert instruction.startswith("review it")


def test_an_agent_without_a_scope_starts_with_no_notes(tmp_path):

    async def main():
        team = mock_team("mem2")
        team.agent_memory = _memory(tmp_path)
        team.agent_defs.define("plain", system_prompt="do it")
        await team.spawn_subagent("look at this", subagent_type="plain")
        return _spawned(team, "plain")

    assert asyncio.run(main()) == "do it"
