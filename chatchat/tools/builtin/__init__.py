from __future__ import annotations

from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL
from chatchat.tool import Tool

from . import messaging, output, plan, questions, skills, subagents, tasks, teams

ORDER = (
    "Agent",
    "SendMessage",
    "TaskOutput",
    "TaskStop",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskList",
    "TaskGet",
    "TaskUpdate",
    "Skill",
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    STRUCTURED_OUTPUT_TOOL,
)

_MODULES = (subagents, messaging, tasks, skills, teams, plan, questions, output)


def builtin_tools(team) -> list[Tool]:
    """The runtime's own tools for this team, in the order a model reads them.

    Each module decides what it can offer from the team it is given; this
    function only decides the order, so the schema list never reshuffles
    because a capability was added or dropped.
    """
    offered = {}
    for module in _MODULES:
        for tool in module.tools(team):
            offered[tool.name] = tool
    return [offered[name] for name in ORDER if name in offered]
