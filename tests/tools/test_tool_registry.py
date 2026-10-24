"""The registry decides what one team offers and who wins a name collision."""

import asyncio

from helpers import mock_team

from chatchat.tool import Tool
from chatchat.tools import ToolRegistry, builtin_tools

SEND_MESSAGE = "SendMessage"


def _team(root, **kw):
    root.mkdir(parents=True, exist_ok=True)

    async def main():
        return mock_team("team", tasks_dir=root, mailbox_dir=root, **kw)

    return asyncio.run(main())


def _host_tool(name):
    return Tool(tool=lambda context: "host", name=name, description="a host tool")


def test_the_runtime_version_of_a_name_is_the_one_offered(tmp_path):
    team = _team(tmp_path)
    registry = ToolRegistry(builtin_tools(team), [_host_tool(SEND_MESSAGE)])
    names = [schema["name"] for schema in registry.schemas(team.tool_context)]
    assert names.count(SEND_MESSAGE) == 1
    assert registry.schemas(team.tool_context)[names.index(SEND_MESSAGE)]["description"] != "a host tool"


def test_a_host_tool_is_appended_after_the_runtime_ones(tmp_path):
    team = _team(tmp_path)
    registry = ToolRegistry(builtin_tools(team), [_host_tool("Read")])
    names = [schema["name"] for schema in registry.schemas(team.tool_context)]
    assert names[-1] == "Read"
    assert names[: len(names) - 1] == [tool.name for tool in builtin_tools(team)]


def test_dispatch_only_ever_finds_the_runtime_tools(tmp_path):
    team = _team(tmp_path)
    registry = ToolRegistry(builtin_tools(team), [_host_tool("Read")])
    assert registry.find_own(SEND_MESSAGE) is not None
    assert registry.find_own("Read") is None


def test_a_capability_that_is_off_takes_its_tools_with_it(tmp_path):
    names = {tool.name for tool in builtin_tools(_team(tmp_path / "bare", multi_agent=False))}
    assert {"Agent", "TaskCreate", "TaskList", "TaskGet", "TaskUpdate"} <= names
    assert not {"SendMessage", "TaskOutput", "TaskStop", "TeamCreate", "TeamDelete"} & names
    assert not {"AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "StructuredOutput", "Skill"} & names


def test_the_order_holds_when_capabilities_come_and_go(tmp_path):
    team = _team(tmp_path)
    team.ask_user = lambda agent, questions: []
    team.tools.set_output_schema({"type": "object", "properties": {}, "additionalProperties": False})
    names = [tool.name for tool in builtin_tools(team)]
    assert names[:5] == ["Agent", "SendMessage", "TaskOutput", "TaskStop", "TeamCreate"]
    assert names[-4:] == ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "StructuredOutput"]
    assert names.index("EnterPlanMode") < names.index("ExitPlanMode")
