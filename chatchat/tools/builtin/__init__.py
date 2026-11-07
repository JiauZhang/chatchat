from __future__ import annotations

from chatchat.tool import Tool
from chatchat.tools.names import CORE_TOOLS

from . import messaging, subagents, skills, tasks, teams


def builtin_tools(team) -> list[Tool]:
    """The runtime's own tools for this team, in the order a model reads them.

    Each module decides what it can offer from the team it is given; this
    function only decides the order, so the schema list never reshuffles
    because a capability was added or dropped.
    """
    offered = {}
    for module in (subagents, messaging, tasks, skills, teams):
        for tool in module.tools(team):
            offered[tool.name] = tool
    return [offered[name] for name in CORE_TOOLS if name in offered]
