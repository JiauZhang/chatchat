from __future__ import annotations

import inspect

from chatchat.team.plan import APPROVE, AUTO_ACCEPT, ENTER_TEXT, plan_file, plan_question, read_plan
from chatchat.tool import Tool, no_arguments, tool


@tool(
    name="EnterPlanMode",
    description="""Ask to switch this session into plan mode before starting anything but a trivial change.
In plan mode nothing that writes or changes state runs, so you can explore and design the approach
and have it approved before touching the project.""",
    parameters=no_arguments(),
)
async def enter_plan_mode(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    if str(getattr(team.hooks, "permission_mode", "")) == "plan":
        return "Already in plan mode."
    team.set_plan_mode("plan")
    return ENTER_TEXT.format(path=plan_file(team))


@tool(
    name="ExitPlanMode",
    description="Present the plan you wrote to the user and leave plan mode once they approve it.",
    parameters=no_arguments(),
)
async def exit_plan_mode(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    plan = read_plan(team)
    if not plan:
        return f"Error: nothing has been written to {plan_file(team)} yet."
    if team.ask_user is None:
        return "Error: no one can approve a plan in this session."
    answers = team.ask_user(agent, [plan_question()])
    if inspect.isawaitable(answers):
        answers = await answers
    choice = str(answers[0] if answers else "")
    if choice == AUTO_ACCEPT:
        team.set_plan_mode("acceptEdits")
        return f"The user approved the plan and wants the edits applied without further prompts.\n\n{plan}"
    if choice == APPROVE:
        team.set_plan_mode("default")
        return f"The user approved the plan.\n\n{plan}"
    return "The user did not approve the plan. Stay in plan mode and ask what they want changed."


def tools(team) -> list[Tool]:
    return [enter_plan_mode, exit_plan_mode] if team.ask_user is not None else []
