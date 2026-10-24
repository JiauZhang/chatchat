import asyncio

from chatchat.runtime.tool_runner import ToolRunner


class _Outcome:
    def __init__(self, text="", blocks=None, additional_context=""):
        self.text = text
        self.blocks = blocks or []
        self.additional_context = additional_context


class _Call:
    def __init__(self, name, tool_input=None, tool_use_id="t1"):
        self.name = name
        self.input = tool_input or {}
        self.id = tool_use_id


def test_what_a_tool_said_comes_back_to_the_model():
    async def execute(call):
        return _Outcome(text="done")

    runner = ToolRunner(execute=execute, agent_name="a")

    async def main():
        return await runner.run([_Call("Read")])

    outcomes = asyncio.run(main())
    assert outcomes[0].as_result() == {"type": "tool_result", "tool_use_id": "t1", "content": "done"}


def test_a_tool_that_returns_blocks_says_them_too():
    async def execute(call):
        return _Outcome(text="done", blocks=[{"type": "text", "text": "extra"}])

    runner = ToolRunner(execute=execute, agent_name="a")

    async def main():
        return await runner.run([_Call("Read")])

    outcomes = asyncio.run(main())
    assert outcomes[0].content == [{"type": "text", "text": "done"}, {"type": "text", "text": "extra"}]


def test_what_a_tool_wants_to_add_rides_along_the_answer():
    async def execute(call):
        return _Outcome(text="done", additional_context="and one more thing")

    runner = ToolRunner(execute=execute, agent_name="a")

    async def main():
        return await runner.run([_Call("Read")])

    outcomes = asyncio.run(main())
    message = ToolRunner.as_message(outcomes)
    assert message["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "done"},
        {"type": "text", "text": "and one more thing"},
    ]


def test_the_tools_run_in_the_order_they_were_asked_for():
    asked = []

    async def execute(call):
        asked.append(call.name)
        return _Outcome(text=call.name)

    runner = ToolRunner(execute=execute, agent_name="a")

    async def main():
        return await runner.run([_Call("Read"), _Call("Bash"), _Call("Grep")])

    asyncio.run(main())
    assert asked == ["Read", "Bash", "Grep"]
