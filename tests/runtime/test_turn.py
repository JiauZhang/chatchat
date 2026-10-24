import asyncio

from chatchat.client import MockClient, ToolUse
from chatchat.team.team import Team


def _team(handler):
    """A team, built where it can be built: inside a running loop."""
    return Team("demo", MockClient(handler=handler))


def test_a_turn_is_what_the_model_said():
    async def respond(messages, tools=None, *, stream_cb=None):
        return "the answer"

    async def main():
        team = _team(respond)
        return await team.lead.chat("the question")

    assert asyncio.run(main()) == "the answer"


def test_the_tools_the_model_asked_for_run_and_answer_it():
    async def respond(messages, tools=None, *, stream_cb=None):
        texts = [c for c in (m.get("content") for m in messages) if isinstance(c, str)]
        if any("look" in c for c in texts):
            return "saw it"
        return [ToolUse("Read", {"path": "x"}, "t1")]

    async def main():
        team = _team(respond)
        team.lead.team.execute_tool = _tool_saying("looked")
        return await team.lead.chat("look at x")

    assert asyncio.run(main()) == "saw it"


def test_the_turn_limit_stops_the_loop():
    calls = {"n": 0}

    async def respond(messages, tools=None, *, stream_cb=None):
        calls["n"] += 1
        return [ToolUse("Read", {"path": "x"}, f"t{calls['n']}")]

    async def main():
        team = _team(respond)
        team.lead.team.execute_tool = _tool_saying("looked")
        team.lead.max_turns = 2
        return await team.lead.chat("go")

    answer = asyncio.run(main())
    assert "turn limit" in answer
    assert calls["n"] == 2


def test_a_hook_that_refuses_the_prompt_is_what_the_agent_says():
    async def respond(messages, tools=None, *, stream_cb=None):
        return "never reached"

    async def main():
        team = _team(respond)
        team.hooks.on("UserPromptSubmit", fn=lambda inp: False)
        return await team.lead.chat("go")

    answer = asyncio.run(main())
    assert answer != "never reached"


def test_what_the_model_thought_is_kept_with_its_answer():
    async def respond(messages, tools=None, *, stream_cb=None):
        if stream_cb:
            stream_cb("thinking about it", "reason")
        return "done"

    async def main():
        team = _team(respond)
        await team.lead.chat("go")
        return team.lead.messages[-1]

    message = asyncio.run(main())
    assert message["thinking"] == "thinking about it"
    assert message["content"] == "done"


def _tool_saying(text):
    """A tool that says one thing."""

    async def execute(*args, **kwargs):
        return _Outcome(text)

    return execute


class _Outcome:
    def __init__(self, text):
        self.text = text
        self.blocks = []
        self.additional_context = ""
