"""A sub-agent asked to work isolated runs where the host put it, and gives it back."""

import asyncio
from pathlib import Path

from chatchat.team.agents import AgentDefinition
from chatchat.tool import ToolContext
from helpers import mock_team


def _seen_text(messages):
    return "\n".join(str(message.get("content") or "") for message in messages if isinstance(message, dict))


def _team(name, root, note="", seen=None):
    async def handler(messages, tools=None, *, stream_cb=None):
        if seen is not None:
            seen.append(_seen_text(messages))
        return "the answer"

    team = mock_team(name, handler=handler, tool_context=ToolContext(cwd=root))
    allocated = []
    released = []

    async def start(label):
        path = Path(root) / "isolated" / label
        path.mkdir(parents=True)
        allocated.append((label, str(path)))
        return str(path)

    async def end(path):
        released.append(path)
        return note

    team.isolation_start = start
    team.isolation_end = end
    return team, allocated, released


async def _run(team, **input):
    return (await team.execute_tool("Agent", {"prompt": "look into it", **input}, team.lead)).text


def test_a_sub_agent_asked_for_isolation_runs_in_the_directory_the_host_made(tmp_path):
    seen = []

    async def main():
        team, allocated, _released = _team("iso1", tmp_path, seen=seen)
        text = await _run(team, isolation="worktree")
        return text, allocated

    text, allocated = asyncio.run(main())
    assert "the answer" in text
    assert len(allocated) == 1
    assert allocated[0][1] in seen[0]
    assert "isolated worktree" in seen[0]


def test_the_isolation_is_given_back_when_the_agent_finishes(tmp_path):
    async def main():
        team, allocated, released = _team("iso2", tmp_path)
        await _run(team, isolation="worktree")
        return allocated, released

    allocated, released = asyncio.run(main())
    assert released == [allocated[0][1]]


def test_work_that_was_left_behind_is_reported_in_the_answer(tmp_path):
    async def main():
        team, _allocated, _released = _team("iso3", tmp_path, note="Its work stays in the worktree /w.")
        return await _run(team, isolation="worktree")

    assert asyncio.run(main()).endswith("Its work stays in the worktree /w.")


def test_the_agent_definition_can_ask_for_isolation_too(tmp_path):
    async def main():
        team, allocated, _released = _team("iso4", tmp_path)
        team.agent_defs.register(AgentDefinition("builder", system_prompt="build it", isolation="worktree"))
        text = await _run(team, subagent_type="builder")
        return text, allocated

    text, allocated = asyncio.run(main())
    assert "the answer" in text
    assert len(allocated) == 1


def test_isolation_without_a_host_that_can_provide_it_is_refused_by_name(tmp_path):
    async def main():
        team = mock_team("iso5", tool_context=ToolContext(cwd=tmp_path))
        return await team.execute_tool("Agent", {"prompt": "x", "isolation": "worktree"}, team.lead)

    text = asyncio.run(main()).text
    assert text.startswith("Error:") and "isolation needs a provider" in text


def test_a_named_teammate_is_not_offered_isolation_it_would_not_get(tmp_path):
    async def main():
        team, allocated, _released = _team("iso6", tmp_path)
        text = await _run(team, name="worker", isolation="worktree")
        return text, allocated

    text, allocated = asyncio.run(main())
    assert text.startswith("Error:") and "named teammate" in text
    assert allocated == []
