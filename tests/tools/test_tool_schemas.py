"""Every tool a model is offered has to be a schema a model can fill in."""

import asyncio

from helpers import mock_team

from chatchat.tools.builtin import builtin_tools

NO_ARGUMENT_TOOLS = ("TaskList", "TeamDelete", "EnterPlanMode", "ExitPlanMode")
NO_ARGUMENTS = {"type": "object", "properties": {}, "additionalProperties": False}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "description": "The answer."}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _schema_problems(schema, where, problems):
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        if kind != "object":
            problems.append(f"{where}: an object schema must say type=object")
        if "additionalProperties" not in schema:
            problems.append(f"{where}: extra keys are neither allowed nor refused")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return
        for name in schema.get("required") or []:
            if name not in properties:
                problems.append(f"{where}: required {name} is not a property")
        if properties and schema.get("additionalProperties") is not False:
            problems.append(f"{where}: unknown keys are not refused")
        for name, child in properties.items():
            _schema_problems(child, f"{where}.{name}", problems)
        return
    if not str(schema.get("description") or "").strip():
        problems.append(f"{where}: no description")
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            problems.append(f"{where}: array without items")
            return
        _schema_problems(items, f"{where}[]", problems)


def _tool_problems(schemas):
    problems = []
    for schema in schemas:
        if not str(schema.get("description") or "").strip():
            problems.append(f"{schema['name']}: no description")
        input_schema = schema.get("input_schema")
        if not isinstance(input_schema, dict):
            problems.append(f"{schema['name']}: no input_schema")
            continue
        _schema_problems(input_schema, f"{schema['name']}.input_schema", problems)
    return problems


def _read(root, read, *, name="team", multi_agent=True):
    async def main():
        team = mock_team(
            name,
            tasks_dir=root,
            mailbox_dir=root,
            multi_agent=multi_agent,
        )
        team.ask_user = lambda agent, questions: []
        team.set_output_schema(OUTPUT_SCHEMA)
        return read(team)

    return asyncio.run(main())


def _schemas(team):
    return team.tool_schemas(team.tool_context)


def _by_name(team, name):
    return next(schema for schema in _schemas(team) if schema["name"] == name)


def test_every_tool_the_model_sees_has_a_fillable_schema(tmp_path):
    schemas = _read(tmp_path, _schemas)
    names = {schema["name"] for schema in schemas}
    assert {"TaskCreate", "TaskUpdate", "TaskOutput", "AskUserQuestion"} <= names
    assert _tool_problems(schemas) == []


def test_no_tool_description_is_left_empty(tmp_path):
    assert _read(tmp_path, lambda team: [t.name for t in builtin_tools(team) if not t.description.strip()]) == []


def test_the_task_read_states_the_wait_the_shell_read_understands(tmp_path):
    properties = _read(tmp_path, lambda team: _by_name(team, "TaskOutput")["input_schema"]["properties"])
    assert properties["block"]["default"] is True
    assert properties["timeout"]["default"] == 30_000
    assert properties["timeout"]["maximum"] == 600_000


def test_the_task_tools_speak_the_names_claude_code_uses(tmp_path):
    def read(team):
        return _by_name(team, "TaskCreate"), _by_name(team, "TaskGet"), _by_name(team, "TaskUpdate")

    create, get, update = _read(tmp_path, read)
    assert create["input_schema"]["properties"]["activeForm"]["type"] == "string"
    assert "taskId" in get["input_schema"]["properties"]
    assert update["input_schema"]["required"] == ["taskId"]
    assert {"addBlocks", "addBlockedBy"} <= set(update["input_schema"]["properties"])
    assert update["input_schema"]["properties"]["status"]["enum"] == ["pending", "in_progress", "completed", "deleted"]


def test_the_agent_tool_asks_for_a_task_not_a_second_system_prompt(tmp_path):
    schema = _read(tmp_path, lambda team: _by_name(team, "Agent")["input_schema"])
    assert schema["required"] == ["prompt"]
    assert set(schema["properties"]) == {"prompt", "subagent_type", "name", "model", "run_in_background", "isolation"}


def test_the_question_tool_states_the_limits_the_runtime_enforces(tmp_path):
    questions = _read(tmp_path, lambda team: _by_name(team, "AskUserQuestion")["input_schema"]["properties"]["questions"])
    assert (questions["minItems"], questions["maxItems"]) == (1, 4)
    options = questions["items"]["properties"]["options"]
    assert (options["minItems"], options["maxItems"]) == (2, 4)
    assert questions["items"]["properties"]["header"]["maxLength"] == 12
    assert questions["items"]["properties"]["multiSelect"]["default"] is False
    assert questions["items"]["required"] == ["question", "header", "options"]


def test_a_team_without_multi_agent_offers_no_message_tools(tmp_path):
    schemas = _read(tmp_path, _schemas, multi_agent=False)
    names = {schema["name"] for schema in schemas}
    assert "SendMessage" not in names and "TaskStop" not in names
    assert _tool_problems(schemas) == []


def test_a_tool_needing_no_arguments_says_so(tmp_path):
    schemas = _read(tmp_path, lambda team: {s["name"]: s["input_schema"] for s in _schemas(team)})
    assert [schemas[name] for name in NO_ARGUMENT_TOOLS] == [NO_ARGUMENTS] * len(NO_ARGUMENT_TOOLS)


def test_the_structured_output_tool_carries_the_schema_it_was_given(tmp_path):
    schema = _read(tmp_path, lambda team: _by_name(team, "StructuredOutput")["input_schema"])
    assert schema["required"] == ["answer"]
    assert schema["properties"]["answer"]["type"] == "string"


def test_the_tool_list_holds_still_across_calls(tmp_path):
    names = _read(tmp_path, lambda team: [[schema["name"] for schema in _schemas(team)] for _ in range(3)])
    assert names[0] == names[1] == names[2]
