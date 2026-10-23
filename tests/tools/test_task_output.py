"""Reading a background sub-agent has to mean what its schema says."""

import asyncio

from helpers import mock_team

from chatchat.tool import Tool


async def _slowly(messages, tools=None, *, stream_cb=None):
    await asyncio.sleep(0.05)
    return "the answer"


def _read(name, **input):
    async def main():
        team = mock_team(name, handler=_slowly)
        await team.execute_tool("Agent", {"prompt": "look into it", "run_in_background": True}, team.lead)
        agent_id = next(iter(team.background))
        read = await team.execute_tool("TaskOutput", {"task_id": agent_id, **input}, team.lead)
        return read.text

    return asyncio.run(main())


def test_the_default_waits_and_returns_the_answer():
    text = _read("out1")
    assert "<fetch_result>success</fetch_result>" in text
    assert "<run_state>completed</run_state>" in text
    assert "the answer" in text


def test_block_false_reports_that_it_is_not_ready_yet():
    text = _read("out2", block=False)
    assert "<fetch_result>not_ready</fetch_result>" in text
    assert "<run_state>running</run_state>" in text


def test_a_wait_that_runs_out_is_a_timeout_not_a_failure():
    text = _read("out3", timeout=5)
    assert "<fetch_result>timeout</fetch_result>" in text
    assert "<run_state>running</run_state>" in text
    assert "(no answer yet)" in text


def test_a_longer_wait_than_the_cap_is_clamped_rather_than_refused():
    text = _read("out4", timeout=10_000_000)
    assert "<fetch_result>success</fetch_result>" in text


def test_an_id_that_is_not_a_sub_agent_falls_through_to_the_shell_read():
    def shell(context, task_id: str) -> str:
        return f"shell output of {task_id}"

    async def main():
        team = mock_team("out5", tools=[Tool(tool=shell, name="TaskOutput", description="reads a shell task")])
        return await team.execute_tool("TaskOutput", {"task_id": "bdeadbeef"}, team.lead)

    assert asyncio.run(main()).text == "shell output of bdeadbeef"
