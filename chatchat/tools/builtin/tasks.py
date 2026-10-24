from __future__ import annotations

from chatchat.hooks.output import describe_blocking
from chatchat.tasks.tasks import TASK_STATUSES
from chatchat.tool import Tool, no_arguments, tool


def _open_blockers(tasks, task) -> list[str]:
    unresolved = {t.id for t in tasks if t.open()}
    return [b for b in task.blocked_by if b in unresolved]


@tool(
    name="TaskCreate",
    description="""Create a new task in the shared task list, so the work is tracked and claimable.
Use it for anything with more than one step, and check TaskList first so work is not duplicated.
New tasks are created with status "pending" and no owner: use TaskUpdate with owner to assign one.""",
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": 'A brief, actionable title in imperative form, e.g. "Fix login bug".'},
            "description": {
                "type": "string",
                "description": "What needs to be done, in enough detail for another agent to finish it.",
            },
            "activeForm": {
                "type": "string",
                "description": 'Present continuous form shown while the task is in_progress, e.g. "Running tests".',
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary metadata to attach to the task; any keys are kept.",
                "additionalProperties": True,
            },
        },
        "required": ["subject", "description"],
        "additionalProperties": False,
    },
)
async def task_create(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    subject = str(input.get("subject") or "").strip()
    description = str(input.get("description") or "").strip()
    if not subject or not description:
        return "Error: TaskCreate needs both subject and description"
    task = team.tasks.create(
        subject,
        description,
        active_form=str(input.get("activeForm") or ""),
        metadata=input.get("metadata") or {},
    )
    if agent is not None and not agent._internal:
        created = await team.hooks.execute_task_created_hooks(agent, str(task.id), task.subject, task.description)
        if created.blocking_error is not None:
            team.tasks.delete(str(task.id))
            return f"Error: {describe_blocking(created.blocking_error)}"
    return f"Task #{task.id} created: {task.subject}"


@tool(
    name="TaskList",
    description="List every task in the shared list with its status, owner and open blockers, so work is not duplicated.",
    parameters=no_arguments(),
)
async def task_list(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    tasks = team.tasks.all()
    if not tasks:
        return "No tasks yet"
    lines = []
    for task in tasks:
        blockers = _open_blockers(tasks, task)
        lines.append(
            f"#{task.id} [{task.status}] {task.subject}"
            + (f" ({task.owner})" if task.owner else "")
            + (" [blocked by " + ", ".join(f"#{b}" for b in blockers) + "]" if blockers else "")
        )
    return "\n".join(lines)


@tool(
    name="TaskGet",
    description="Read one task in full, including its description and the dependencies in both directions.",
    parameters={
        "type": "object",
        "properties": {"taskId": {"type": "string", "description": "The ID of the task to retrieve."}},
        "required": ["taskId"],
        "additionalProperties": False,
    },
)
async def task_get(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    task = team.tasks.get(input.get("taskId") or "")
    if task is None:
        return "Error: task not found"
    lines = [f"Task #{task.id}: {task.subject}", f"Status: {task.status}", f"Description: {task.description}"]
    if task.owner:
        lines.append(f"Owner: {task.owner}")
    if task.blocked_by:
        lines.append("Blocked by: " + ", ".join(f"#{b}" for b in task.blocked_by))
    if task.blocks:
        lines.append("Blocks: " + ", ".join(f"#{b}" for b in task.blocks))
    return "\n".join(lines)


@tool(
    name="TaskUpdate",
    description="""Change a task: move it through pending, in_progress and completed, hand it to an owner,
or link it with addBlocks / addBlockedBy. status "deleted" removes it.
Mark a task in_progress before starting it, and completed only when the work is fully done.""",
    parameters={
        "type": "object",
        "properties": {
            "taskId": {"type": "string", "description": "The ID of the task to update."},
            "subject": {"type": "string", "description": "New subject for the task."},
            "description": {"type": "string", "description": "New description for the task."},
            "activeForm": {
                "type": "string",
                "description": 'Present continuous form shown while it is in_progress, e.g. "Running tests".',
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "deleted"],
                "description": "New status for the task.",
            },
            "owner": {"type": "string", "description": "Agent name to assign the task to."},
            "metadata": {
                "type": "object",
                "description": "Metadata keys to merge into the task; set a key to null to delete it.",
                "additionalProperties": True,
            },
            "addBlocks": {
                "type": "array",
                "items": {"type": "string", "description": "Task ID."},
                "description": "Task IDs that cannot start until this one completes.",
            },
            "addBlockedBy": {
                "type": "array",
                "items": {"type": "string", "description": "Task ID."},
                "description": "Task IDs that must complete before this one can start.",
            },
        },
        "required": ["taskId"],
        "additionalProperties": False,
    },
)
async def task_update(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    task_id = input.get("taskId")
    if not task_id:
        return "Error: TaskUpdate needs a taskId"
    if input.get("status") == "deleted":
        return f"Task #{task_id} deleted" if team.tasks.delete(task_id) else "Error: task not found"
    fields = {
        key: input[key] for key in ("subject", "description", "status", "owner", "metadata") if input.get(key) is not None
    }
    if input.get("activeForm") is not None:
        fields["active_form"] = input["activeForm"]
    status = fields.get("status")
    if status is not None and status not in TASK_STATUSES:
        return f'Error: status must be one of {", ".join(TASK_STATUSES)}, or "deleted" to remove the task'
    parts = [f"{key} -> {value}" if key == "status" else key for key, value in fields.items()]
    for key, forward in (("addBlocks", True), ("addBlockedBy", False)):
        wanted = input.get(key) or []
        linked = 0
        for other in wanted:
            ok = team.tasks.block(task_id, other) if forward else team.tasks.block(other, task_id)
            if not ok:
                return f"Error: task #{other} does not exist to link"
            linked += 1
        if linked:
            parts.append(key)
    if not parts:
        return "Error: TaskUpdate was given nothing to change"
    if fields.get("status") == "completed" and agent is not None and not agent._internal:
        task = team.tasks.get(task_id)
        if task is not None:
            done = await team.hooks.execute_task_completed_hooks(agent, str(task.id), task.subject, task.description)
            if done.blocking_error is not None:
                return f"Error: {describe_blocking(done.blocking_error)}"
    if fields and team.tasks.update(task_id, **fields) is None:
        return f"Error: no task with id '{task_id}'"
    return f"Task #{task_id} updated: " + ", ".join(parts)


def tools(team) -> list[Tool]:
    if team.tasks is None:
        return []
    return [task_create, task_list, task_get, task_update]
