from __future__ import annotations

from chatchat.tool import Tool, no_arguments, tool


@tool(
    name="TeamCreate",
    description="""Gather the work under one named team. The team and its task list are the same thing:
every task you create from now on belongs to it, and so does every teammate you spawn.
Call it once, before the work is divided.""",
    parameters={
        "type": "object",
        "properties": {
            "team_name": {"type": "string", "description": "Name of the team to gather the work under."},
            "description": {"type": "string", "description": "What the team is working on."},
        },
        "required": ["team_name"],
        "additionalProperties": False,
    },
)
async def team_create(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    name = str(input.get("team_name") or "").strip()
    if not name:
        return "Error: TeamCreate needs a team_name"
    try:
        team.join_team(name, str(input.get("description") or "").strip())
    except ValueError as exc:
        return f"Error: {exc}"
    return (
        f'Team "{name}" is active. Its task list is the team: everything '
        f"you add with TaskCreate is shared with the teammates you spawn "
        f"from now on."
    )


@tool(
    name="TeamDelete",
    description="""Throw away the current team and its task list once the work is done.
It refuses while a teammate is still running, so stop them first with TaskStop.""",
    parameters=no_arguments(),
)
async def team_delete(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    try:
        team.leave_team()
    except ValueError as exc:
        return f"Error: {exc}"
    return "Cleaned up the team record and its task list."


def tools(team) -> list[Tool]:
    return [team_create, team_delete] if team.multi_agent else []
