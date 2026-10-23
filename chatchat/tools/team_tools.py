from __future__ import annotations

import asyncio
import inspect

from chatchat.hooks.output import describe_blocking
from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL, mismatch
from chatchat.tasks.tasks import TASK_STATUSES
from chatchat.team.agents import resolve_agent_model
from chatchat.team.plan import APPROVE, AUTO_ACCEPT, ENTER_TEXT, plan_file, plan_question, read_plan
from chatchat.tool import Tool, ToolContext, describe_tools, tool

TASK_DEFAULT_TIMEOUT_MS = 30_000
TASK_MAX_TIMEOUT_MS = 600_000

MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_HEADER_CHARS = 12

SUBAGENT_INSTRUCTION = "You are an autonomous sub-agent. Complete the task and give your final answer."

AGENT_DESCRIPTION = """Run a sub-agent on one task and return its final answer.
Without a name it is a one-off sub-agent: it runs synchronously, answers, then is reclaimed.
With a name it becomes a persistent teammate that keeps a mailbox, so assign it work with SendMessage.
subagent_type picks its AgentDefinition; general-purpose is the default."""


def _no_arguments() -> dict:
    return {"type": "object", "properties": {}, "additionalProperties": False}


@tool(
    name="SendMessage",
    description="""Send a message to a teammate by name, or "*" to broadcast to every other teammate.
The message lands in their mailbox and is injected on their next idle turn, so do not re-send it or poll them:
their answer arrives as a teammate-message.""",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": 'Teammate name, or "*" for every other teammate.'},
            "message": {"type": "string", "description": "Plain text, delivered to the recipient as written."},
        },
        "required": ["to", "message"],
        "additionalProperties": False,
    },
)
async def send_message(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    to = input.get("to", "")
    message = input.get("message", "") or ""
    note = "Do NOT re-send or poll them; wait for their teammate-message back."
    if to == "*":
        recipients = [a for a in team.agents.values() if a.name != agent.name]
        if not recipients:
            return "No teammates to broadcast to (you are the only agent)"
        for r in recipients:
            r.inbox.write(agent.name, message)
        if agent is not None and not agent._internal:
            await team.hooks.execute_notification_hooks(agent, "message", message, f"{agent.name} -> *")
        names = ", ".join(r.name for r in recipients)
        return f"Told {len(recipients)} teammate(s): {names}. {note}"
    recipient = team.get_by_name(to)
    if recipient is None:
        return f'Error: unknown teammate "{to}"'
    recipient.inbox.write(agent.name, message)
    if agent is not None and not agent._internal:
        await team.hooks.execute_notification_hooks(agent, "message", message, f"{agent.name} -> {to}")
    return f"Sent to {to}, who reads it on their next idle turn. {note}"


@tool(
    name="Agent",
    description=AGENT_DESCRIPTION,
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The task for the agent to perform."},
            "subagent_type": {
                "type": "string",
                "description": 'Type of specialized agent to use, from the available subagent types. Defaults to "general-purpose".',
            },
            "name": {
                "type": "string",
                "description": "Name for a persistent teammate that keeps a mailbox; omit it for a one-off sub-agent.",
            },
            "model": {
                "type": "string",
                "description": 'Optional model override: "provider/model", a bare name in the session provider, or "inherit".',
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Run this one-off sub-agent in the background; its answer arrives in your inbox when it finishes.",
            },
            "isolation": {
                "type": "string",
                "enum": ["worktree"],
                "description": "Run the agent on an isolated copy of the repository in a temporary git worktree, so its edits "
                "never touch the checked-out directory. The worktree is removed when the agent left nothing behind, and "
                "kept, with its path reported, when it left work in it.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
)
async def create_agent(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    prompt = input.get("prompt", "")
    name = input.get("name")
    subagent_type = input.get("subagent_type")
    if subagent_type and team.agent_defs.find(str(subagent_type)) is None:
        known = ", ".join(name for name, _desc in team.agent_defs.describe())
        return f'Error: unknown subagent_type "{subagent_type}"; available: {known or "none"}.'
    isolation = str(input.get("isolation") or "")
    background = bool(input.get("run_in_background"))
    if isolation and name:
        return "Error: isolation is for a one-off sub-agent; a named teammate works in the session directory."
    if background and name:
        return "Error: a named teammate already works in the background; run_in_background is for a one-off sub-agent."
    if background and agent is not None and agent._internal:
        return (
            "Error: only the agent that owns the conversation can send work to the background. Finish your own sub-agent here."
        )
    if name and getattr(team, "multi_agent", True):
        if agent is not None and not agent.ctx.leader:
            return "Error: Teammates cannot spawn other teammates — the team roster is flat."
        teammate = team.create_agent(
            str(name), instruction=SUBAGENT_INSTRUCTION, model=input.get("model"), depth=getattr(agent, "depth", 0) + 1
        )
        team.parents[teammate.agent_id] = agent.agent_id
        team.children.setdefault(agent.agent_id, set()).add(teammate.agent_id)
        teammate.submit(prompt)
        return (
            f'Teammate "{name}" spawned and idle. Assign work with '
            f'SendMessage (to: "{name}"); stop it with TaskStop '
            f"(agent_id: {teammate.agent_id})."
        )
    if background:
        try:
            agent_id = await team.spawn_background_subagent(
                prompt,
                agent or team.lead,
                subagent_type=subagent_type,
                instruction=SUBAGENT_INSTRUCTION,
                model=input.get("model"),
                depth=getattr(agent, "depth", 0) + 1,
                tool_use_id=tool_use_id,
                isolation=isolation,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return (
            f"{agent_id.rsplit('@', 1)[0]} is running in the background. "
            f"Do not wait for it; its answer arrives in your inbox when "
            f"it is done (agent_id: {agent_id}; stop it with TaskStop)."
        )
    if agent is not None and not agent._internal:
        created = await team.hooks.execute_task_created_hooks(agent, f"{agent.name}:sub", prompt)
        if created.blocking_error is not None:
            return f"Error: {describe_blocking(created.blocking_error)}"
    try:
        result = await team.spawn_subagent(
            prompt,
            subagent_type=subagent_type,
            instruction=SUBAGENT_INSTRUCTION,
            model=input.get("model"),
            depth=getattr(agent, "depth", 0) + 1,
            tool_use_id=tool_use_id,
            isolation=isolation,
        )
    except ValueError as exc:
        return f"Error: {exc}"
    if agent is not None and not agent._internal:
        done = await team.hooks.execute_task_completed_hooks(agent, f"{agent.name}:sub", prompt)
        if done.blocking_error is not None:
            return f"{result}\n{describe_blocking(done.blocking_error)}"
    return result


def _wait_seconds(value) -> float:
    try:
        milliseconds = TASK_DEFAULT_TIMEOUT_MS if value is None else int(value)
    except (TypeError, ValueError):
        milliseconds = TASK_DEFAULT_TIMEOUT_MS
    return max(0, min(milliseconds, TASK_MAX_TIMEOUT_MS)) / 1000


async def _still_running(team, agent_id: str, sub) -> bool:
    return agent_id in team.background or not await sub.idle()


async def _wait_for_agent(team, agent_id: str, sub, seconds: float) -> None:
    task = team.background.get(agent_id)
    if task is not None:
        await asyncio.wait({task}, timeout=seconds)
        return
    if await sub.idle():
        return
    try:
        await sub.wait_idle(seconds)
    except asyncio.TimeoutError:
        pass


@tool(
    name="TaskOutput",
    description="""Read what a background task has produced: a background shell command's output, or a sub-agent's answer.
Waits for the task by default, so a timeout report means it is still running rather than that it failed.""",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The ID of the background task or sub-agent to read."},
            "block": {"type": "boolean", "default": True, "description": "Wait for the task to finish before returning."},
            "timeout": {
                "type": "integer",
                "default": TASK_DEFAULT_TIMEOUT_MS,
                "minimum": 0,
                "maximum": TASK_MAX_TIMEOUT_MS,
                "description": f"Milliseconds to wait when block is true (max {TASK_MAX_TIMEOUT_MS}).",
            },
        },
        "required": ["task_id"],
        "additionalProperties": False,
    },
)
async def task_output(context, team, agent, input: dict, tool_use_id: str = "") -> str | None:
    target = str(input.get("task_id") or "").strip()
    if not target:
        return None
    agent_id = target if "@" in target else team.agent_id(target)
    sub = team.agents.get(agent_id)
    if sub is None:
        return None
    block = input.get("block") is not False
    if block:
        await _wait_for_agent(team, agent_id, sub, _wait_seconds(input.get("timeout")))
    running = await _still_running(team, agent_id, sub)
    body = sub.last_assistant(start=0) or ""
    if not running:
        retrieval = "success"
    elif block:
        retrieval = "timeout"
    else:
        retrieval = "not_ready"
    return "\n".join(
        [
            f"<fetch_result>{retrieval}</fetch_result>",
            f"<task_ref>{target}</task_ref>",
            "<task_kind>agent</task_kind>",
            f"<run_state>{'running' if running else 'completed'}</run_state>",
            body if body.strip() else "(no answer yet)",
        ]
    )


@tool(
    name="TaskStop",
    description="Permanently stop a background task or one of your own sub-agents, by its task id.",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "The ID of the task or sub-agent to stop."}},
        "required": ["task_id"],
        "additionalProperties": False,
    },
)
async def task_stop(context, team, agent, input: dict, tool_use_id: str = "") -> str | None:
    target = str(input.get("task_id") or "").strip()
    if not target:
        return "Error: TaskStop needs a task_id"
    agent_id = target if "@" in target else team.agent_id(target)
    if agent_id not in team.agents:
        return None
    children = team.children.get(agent.agent_id, set()) if agent is not None else set()
    if agent_id not in children:
        return f'Error: "{target}" is not your sub-agent'
    sub = team.agents.get(agent_id)
    if sub is not None:
        await team.stop_agent(sub)
    return f"agent {agent_id} stopped"


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
    parameters=_no_arguments(),
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


@tool(
    name="Skill",
    description="""Load the full instructions of one skill when the task at hand is one it covers; the steps come from this call.
The available skills are listed in system-reminder messages in the conversation, so a skill the user added mid-session,
or one that just activated on a touched file, shows up there.""",
    parameters={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "The skill name from the listing."},
            "args": {"type": "string", "description": "What the skill should work on."},
        },
        "required": ["skill"],
        "additionalProperties": False,
    },
)
async def use_skill(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    name = str(input.get("skill") or "").strip()
    if not name:
        return "Error: Skill needs the name of the skill"
    registry = team.skills
    available = ", ".join(other.name for other in registry.for_model())
    skill = registry.get(name)
    if skill is None:
        return f"Error: no such skill: {name}. Available: {available or 'none'}"
    if skill.disable_model_invocation:
        return (
            f'Error: "{name}" is only for the user to ask for by name, so '
            f"it cannot be loaded from here. Available: "
            f"{available or 'none'}"
        )
    args = str(input.get("args") or "").strip()
    if skill.allowed_tools and team._skills_granted is not None:
        team._skills_granted(skill.allowed_tools)
    if skill.model and agent is not None:
        current = f"{agent.client.provider}/{agent.client.model}"
        model, problem = resolve_agent_model(skill.model, current)
        if problem:
            return f"Error: {problem}"
        if model is not None and model != current:
            agent.client = team._client_for(agent.instruction, model=model)
    return skill.render(args)


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
    parameters=_no_arguments(),
)
async def team_delete(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    try:
        team.leave_team()
    except ValueError as exc:
        return f"Error: {exc}"
    return "Cleaned up the team record and its task list."


def _question_problems(questions) -> str:
    if not isinstance(questions, list) or not questions:
        return "AskUserQuestion needs at least one question"
    if len(questions) > MAX_QUESTIONS:
        return f"AskUserQuestion takes at most {MAX_QUESTIONS} questions"
    for index, question in enumerate(questions, start=1):
        if not str((question or {}).get("question") or "").strip():
            return f"question {index} needs its text"
        header = str(question.get("header") or "")
        if not header.strip():
            return f"question {index} needs a header"
        if len(header) > MAX_HEADER_CHARS:
            return f"question {index} has a header over {MAX_HEADER_CHARS} characters"
        options = question.get("options") or []
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            return f"question {index} needs between {MIN_OPTIONS} and {MAX_OPTIONS} options"
        for option in options:
            label = str((option or {}).get("label") or "").strip()
            if not label:
                return f"question {index} has an option without a label"
            if not str(option.get("description") or "").strip():
                return f'question {index} has an option ("{label}") without a description'
    return ""


@tool(
    name="EnterPlanMode",
    description="""Ask to switch this session into plan mode before starting anything but a trivial change.
In plan mode nothing that writes or changes state runs, so you can explore and design the approach
and have it approved before touching the project.""",
    parameters=_no_arguments(),
)
async def enter_plan_mode(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    if str(getattr(team.hooks, "permission_mode", "")) == "plan":
        return "Already in plan mode."
    team.set_plan_mode("plan")
    return ENTER_TEXT.format(path=plan_file(team))


@tool(
    name="ExitPlanMode",
    description="Present the plan you wrote to the user and leave plan mode once they approve it.",
    parameters=_no_arguments(),
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


@tool(
    name="AskUserQuestion",
    description=f"""Ask the human 1 to {MAX_QUESTIONS} questions and wait for the answers, when a choice they can make
would change what you do.
Give each question {MIN_OPTIONS} to {MAX_OPTIONS} options worth picking; they can also answer in their own words.
When they have to compare concrete results, put the artifact on the option as preview.""",
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS,
                "description": f"Questions to ask the user (1-{MAX_QUESTIONS}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": 'The complete question: clear, specific and ending with "?".',
                        },
                        "header": {
                            "type": "string",
                            "maxLength": MAX_HEADER_CHARS,
                            "description": f'Very short label shown as a chip/tag (max {MAX_HEADER_CHARS} chars), e.g. "Auth method".',
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "default": False,
                            "description": "Allow several options to be picked. Use it when the choices are not mutually exclusive.",
                        },
                        "options": {
                            "type": "array",
                            "minItems": MIN_OPTIONS,
                            "maxItems": MAX_OPTIONS,
                            "description": f'The {MIN_OPTIONS}-{MAX_OPTIONS} choices. Do not add an "Other" option: one is offered automatically.',
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "Display text the user picks: one to five words naming the choice.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "What the option means, or what happens if it is chosen, including the trade-off.",
                                    },
                                    "preview": {
                                        "type": "string",
                                        "description": "The artifact this option would produce, shown beside the options while it is picked. Use it when the user has to compare concrete results, not for a plain preference. Only single-select questions show previews.",
                                    },
                                },
                                "required": ["label", "description"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["question", "header", "options"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
)
async def ask_user(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    questions = input.get("questions") or []
    problem = _question_problems(questions)
    if problem:
        return f"Error: {problem}"
    await team.hooks.execute_elicitation_hooks(agent, str(questions[0].get("question") or ""))
    answers = team.ask_user(agent, questions)
    if asyncio.iscoroutine(answers):
        answers = await answers
    lines = []
    for index, question in enumerate(questions):
        answer = str(answers[index] if index < len(answers) else "")
        answer = answer or "no answer"
        lines.append(f"{question['question']}: {answer}")
    await team.hooks.execute_elicitation_result_hooks(agent, "\n".join(lines))
    return "The user answered:\n" + "\n".join(lines) + "\nCarry on with those answers."


@tool(
    name=STRUCTURED_OUTPUT_TOOL,
    description="""Return your final answer as the structured payload below.
Call it exactly once, at the end of the work; nothing you say in prose counts as the answer.
The payload must match this schema.""",
    parameters=None,
)
async def structured_output(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    problem = mismatch(team.output_schema or {}, input)
    if problem:
        return f"Error: output does not match the required schema: {problem}"
    team.structured_output = dict(input)
    return "Structured output recorded. Finish the run now."


def team_tools(team) -> list[Tool]:
    """The Tool instances available to this team, one list per capability."""
    tools = [create_agent.with_description(team._create_agent_description())]
    if team.multi_agent:
        tools += [send_message, task_output, task_stop, team_create, team_delete]
    if team.tasks is not None:
        tools += [task_create, task_list, task_get, task_update]
    if team.skills.all():
        tools.append(use_skill)
    if team.ask_user is not None:
        tools += [ask_user, enter_plan_mode, exit_plan_mode]
    if team.output_schema is not None:
        tools.append(structured_output.with_parameters(team.output_schema))
    return tools


def find_team_tool(team, name: str) -> Tool | None:
    return next((t for t in team_tools(team) if t.name == name), None)


class TeamSchemasMixin:
    def tool_schemas(self, context: ToolContext) -> list[dict]:
        tools = team_tools(self)
        names = {t.name for t in tools}
        return describe_tools(tools, context) + [
            t for t in describe_tools(self._injected_tools, context) if t["name"] not in names
        ]
