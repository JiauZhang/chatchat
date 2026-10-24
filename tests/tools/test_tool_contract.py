"""The tool contract every later refactor has to keep: what a model is told.

The JSON beside this file is the schema list a model sees, captured before the
tool layer was split out of one module. A change here is a change in what the
model is offered, so it has to be deliberate, and updating the fixture is the
review step.
"""

import asyncio
import json
from pathlib import Path

from helpers import mock_team

CONTRACT = Path(__file__).with_name("tool_contract.json")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "description": "The answer."}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _schemas(root, *, multi_agent=True, rich=True):
    async def main():
        team = mock_team("team", tasks_dir=root, mailbox_dir=root, multi_agent=multi_agent)
        if rich:
            team.ask_user = lambda agent, questions: []
            team.tools.set_output_schema(OUTPUT_SCHEMA)
        return team.tool_schemas(team.tool_context)

    return asyncio.run(main())


def test_the_tool_contract_is_what_the_model_was_promised(tmp_path):
    expected = json.loads(CONTRACT.read_text(encoding="utf-8"))
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _schemas(tmp_path) == expected["team"]
    assert _schemas(plain, multi_agent=False, rich=False) == expected["single_agent"]
