from __future__ import annotations

from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL, mismatch
from chatchat.tool import Tool, tool


@tool(
    name=STRUCTURED_OUTPUT_TOOL,
    description="""Return your final answer as the structured payload below.
Call it exactly once, at the end of the work; nothing you say in prose counts as the answer.
The payload must match this schema.""",
    parameters=None,
)
async def structured_output(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    problem = mismatch(team.tools.output_schema or {}, input)
    if problem:
        return f"Error: output does not match the required schema: {problem}"
    team.tools.structured_output = dict(input)
    return "Structured output recorded. Finish the run now."


def tools(team) -> list[Tool]:
    if team.tools.output_schema is None:
        return []
    return [structured_output.with_parameters(team.tools.output_schema)]
