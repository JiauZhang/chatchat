from __future__ import annotations

from chatchat.enums import ValueStrEnum


class ToolName(ValueStrEnum):
    AGENT = "Agent"
    SEND_MESSAGE = "SendMessage"
    TASK_OUTPUT = "TaskOutput"
    TASK_STOP = "TaskStop"
    TEAM_CREATE = "TeamCreate"
    TEAM_DELETE = "TeamDelete"
    TASK_CREATE = "TaskCreate"
    TASK_LIST = "TaskList"
    TASK_GET = "TaskGet"
    TASK_UPDATE = "TaskUpdate"
    SKILL = "Skill"


AGENT = ToolName.AGENT
SEND_MESSAGE = ToolName.SEND_MESSAGE
TASK_OUTPUT = ToolName.TASK_OUTPUT
TASK_STOP = ToolName.TASK_STOP
TEAM_CREATE = ToolName.TEAM_CREATE
TEAM_DELETE = ToolName.TEAM_DELETE
TASK_CREATE = ToolName.TASK_CREATE
TASK_LIST = ToolName.TASK_LIST
TASK_GET = ToolName.TASK_GET
TASK_UPDATE = ToolName.TASK_UPDATE
SKILL = ToolName.SKILL

CORE_TOOLS = tuple(ToolName)
