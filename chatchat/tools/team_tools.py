from __future__ import annotations

import asyncio
import inspect

from chatchat.runtime.skills import listing_budget
from chatchat.runtime.structured import STRUCTURED_OUTPUT_TOOL
from chatchat.tool import Tool, ToolContext, describe_tools, tool
from chatchat.tasks.cron import human
from chatchat.team.plan import APPROVE, AUTO_ACCEPT, ENTER_TEXT, plan_file, plan_question, read_plan
from chatchat.tasks.tasks import TASK_STATUSES
from chatchat.runtime.structured import mismatch
from chatchat.hooks.output import describe_blocking


@tool(
    name="SendMessage",
    description='Send a message to a teammate by name (or "*" to '
    "broadcast). Messages are delivered to their mailbox "
    "and injected on their next idle turn.",
    parameters={
        "type": "object",
        "properties": {"to": {"type": "string"}, "message": {"type": "string"}},
        "required": ["to", "message"],
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
    description="",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "instruction": {"type": "string"},
            "subagent_type": {"type": "string"},
            "name": {
                "type": "string",
                "description": "Optional "
                "name for a persistent "
                "teammate (team mode): "
                "stays alive with a "
                "mailbox; message it via "
                "SendMessage. Omit for "
                "a one-off sub-agent.",
            },
            "model": {"type": "string", "description": "Optional model override for the spawned agent."},
            "run_in_background": {
                "type": "boolean",
                "description": "Set true for a "
                "one-off sub-agent whose work "
                "should not hold this turn "
                "open. The answer arrives in "
                "your inbox when it finishes.",
            },
        },
        "required": ["prompt"],
    },
)
async def create_agent(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    prompt = input.get("prompt", "")
    cfg = input.get("instruction") or ("You are an autonomous sub-agent. Complete the task and give your final answer.")
    name = input.get("name")
    subagent_type = input.get("subagent_type")
    if subagent_type and team.agent_defs.find(str(subagent_type)) is None:
        known = ", ".join(name for name, _desc in team.agent_defs.describe())
        return f'Error: unknown subagent_type "{subagent_type}"; available: {known or "none"}.'
    background = bool(input.get("run_in_background"))
    if background and name:
        return "Error: a named teammate already works in the background; run_in_background is for a one-off sub-agent."
    if background and agent is not None and agent._internal:
        return (
            "Error: only the agent that owns the conversation can send work to the background. Finish your own sub-agent here."
        )
    if name and getattr(team, "multi_agent", True):
        if agent is not None and not agent.ctx.leader:
            return "Error: Teammates cannot spawn other teammates — the team roster is flat."
        teammate = team.create_agent(str(name), instruction=cfg, model=input.get("model"), depth=getattr(agent, "depth", 0) + 1)
        team.parents[teammate.agent_id] = agent.agent_id
        team.children.setdefault(agent.agent_id, set()).add(teammate.agent_id)
        teammate.submit(prompt)
        return (
            f'Teammate "{name}" spawned and idle. Assign work with '
            f'SendMessage (to: "{name}"); stop it with TaskStop '
            f"(agent_id: {teammate.agent_id})."
        )
    if background:
        agent_id = await team.spawn_background_subagent(
            prompt,
            agent or team.lead,
            subagent_type=subagent_type,
            instruction=cfg,
            model=input.get("model"),
            depth=getattr(agent, "depth", 0) + 1,
            tool_use_id=tool_use_id,
        )
        return (
            f"{agent_id.rsplit('@', 1)[0]} is running in the background. "
            f"Do not wait for it; its answer arrives in your inbox when "
            f"it is done (agent_id: {agent_id}; stop it with TaskStop)."
        )
    if agent is not None and not agent._internal:
        created = await team.hooks.execute_task_created_hooks(agent, f"{agent.name}:sub", prompt)
        if created.blocking_error is not None:
            return f"Error: {describe_blocking(created.blocking_error)}"
    result = await team.spawn_subagent(
        prompt,
        subagent_type=subagent_type,
        instruction=cfg,
        model=input.get("model"),
        depth=getattr(agent, "depth", 0) + 1,
        tool_use_id=tool_use_id,
    )
    if agent is not None and not agent._internal:
        done = await team.hooks.execute_task_completed_hooks(agent, f"{agent.name}:sub", prompt)
        if done.blocking_error is not None:
            return f"{result}\n{describe_blocking(done.blocking_error)}"
    return result


@tool(
    name="TaskOutput",
    description="Read what a background task has produced: a "
    "background shell command's output, or a "
    "sub-agent's answer. Waits for the task by "
    "default, so a timeout report means it is "
    "still running.",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "string"}, "block": {"type": "boolean"}, "timeout": {"type": "integer"}},
        "required": ["task_id"],
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
    body = sub.last_assistant(start=0) or ""
    running = bool(getattr(sub, "busy", False))
    state = "running" if running else "completed"
    return "\n".join(
        [
            f"<fetch_result>{'not_ready' if running else 'success'}</fetch_result>",
            f"<task_ref>{target}</task_ref>",
            "<task_kind>agent</task_kind>",
            f"<run_state>{state}</run_state>",
            body if body.strip() else "(no answer yet)",
        ]
    )


@tool(
    name="TaskStop",
    description="Permanently stop a background task or one of your own sub-agents, by its task id.",
    parameters={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
)
async def task_stop(context, team, agent, input: dict, tool_use_id: str = "") -> str | None:
    target = str(input.get("task_id") or "").strip()
    if not target:
        return "Error: TaskStop needs a task_id"
    agent_id = target if "@" in target else team.agent_id(target)
    if agent_id not in team.agents:
        return None
    if agent_id not in team.children.get(agent.agent_id, set()):
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
    description="Add a task to the team list so the work is "
    "tracked and claimable. Use it for anything "
    "with more than one step; give a short "
    "imperative subject and the full description.",
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "active_form": {"type": "string", "description": "Present continuous label shown while it is running"},
            "metadata": {"type": "object"},
        },
        "required": ["subject", "description"],
    },
)
async def task_create(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    subject = str(input.get("subject") or "").strip()
    description = str(input.get("description") or "").strip()
    if not subject or not description:
        return "Error: TaskCreate needs both subject and description"
    task = team.tasks.create(
        subject, description, active_form=str(input.get("active_form") or ""), metadata=input.get("metadata") or {}
    )
    return f"Task #{task.id} created: {task.subject}"


@tool(
    name="TaskList",
    description="List every task with its status, owner and open blockers. Check it before creating so work is not duplicated.",
    parameters={"type": "object", "properties": {}},
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
    description="Read one task in full.",
    parameters={"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
)
async def task_get(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    task = team.tasks.get(input.get("task_id") or "")
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
    description="Change a task: move it through pending, "
    "in_progress and completed, hand it to an "
    "owner, or link it with add_blocks / "
    'add_blocked_by. status "deleted" removes it. '
    "Mark a task in_progress before starting it.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "active_form": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]},
            "owner": {"type": "string"},
            "metadata": {"type": "object"},
            "add_blocks": {"type": "array", "items": {"type": "string"}},
            "add_blocked_by": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["task_id"],
    },
)
async def task_update(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    task_id = input.get("task_id")
    if not task_id:
        return "Error: TaskUpdate needs a task_id"
    if input.get("status") == "deleted":
        return f"Task #{task_id} deleted" if team.tasks.delete(task_id) else "Error: task not found"
    fields = {
        key: input[key]
        for key in ("subject", "description", "active_form", "status", "owner", "metadata")
        if input.get(key) is not None
    }
    parts = [f"{key} -> {value}" if key == "status" else key for key, value in fields.items()]
    for key, forward in (("add_blocks", True), ("add_blocked_by", False)):
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
    if fields and team.tasks.update(task_id, **fields) is None:
        return f'Error: status must be one of {", ".join(TASK_STATUSES)}, or "deleted" to remove the task'
    return f"Task #{task_id} updated: " + ", ".join(parts)


@tool(
    name="Skill",
    description="",
    parameters={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "The name from the listing."},
            "args": {"type": "string", "description": "What the skill should work on."},
        },
        "required": ["skill"],
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
    return skill.render(args)


@tool(
    name="TeamCreate",
    description="Gather the work under one named team. The "
    "team and its task list are the same thing: "
    "every task you create from now on belongs to "
    "it, and so does every teammate you spawn. "
    "Call it once, before the work is divided.",
    parameters={
        "type": "object",
        "properties": {"team_name": {"type": "string"}, "description": {"type": "string"}},
        "required": ["team_name"],
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
    description="Throw away the current team and its task list "
    "once the work is done. It refuses while a "
    "teammate is still running, so stop them "
    "first with TaskStop.",
    parameters={"type": "object", "properties": {}},
)
async def team_delete(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    try:
        team.leave_team()
    except ValueError as exc:
        return f"Error: {exc}"
    return "Cleaned up the team record and its task list."


@tool(
    name="EnterWorktree",
    description="Only when the user asks for a worktree: make "
    "an isolated git worktree under "
    ".pyclaw/worktrees and move this session into "
    "it, so the work cannot touch the checked-out "
    "directory. Needs a git repository or "
    "WorktreeCreate/WorktreeRemove hooks, and not "
    "already be in one. A worktree of that name "
    "that is still on disk is entered again rather "
    "than recreated.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Optional. "
                "Letters, digits, "
                "dots, dashes and "
                "underscores, "
                'divided by "/"; '
                "up to 64 "
                "characters. A "
                "readable name is "
                "picked when it "
                "is left out, and "
                "this session "
                "keeps using "
                "it.",
            }
        },
    },
)
async def enter_worktree(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    try:
        return await team.enter_worktree(str(input.get("name") or ""))
    except ValueError as exc:
        return f"Error: {exc}"


@tool(
    name="ExitWorktree",
    description="Leave the worktree this session moved into, "
    "back to the original directory. Only worktrees "
    "this session entered; one made by hand or in "
    "another conversation is left alone. action "
    '"keep" leaves the directory and its branch on '
    'disk, "remove" deletes both. remove refuses '
    "while the worktree holds uncommitted files or "
    "commits of its own.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["keep", "remove"]},
            "discard_changes": {
                "type": "boolean",
                "description": 'Only with "remove": '
                "throw away the "
                "uncommitted files and "
                "the commits no branch "
                "else has. Ask the "
                "user first.",
            },
        },
        "required": ["action"],
    },
)
async def exit_worktree(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    return await team.exit_worktree(keep=str(input.get("action") or "") == "keep", discard=bool(input.get("discard_changes")))


MAX_QUESTIONS = 4
MAX_OPTIONS = 4
MAX_HEADER_CHARS = 12


def _question_problems(questions) -> str:
    if not isinstance(questions, list) or not questions:
        return "AskUserQuestion needs at least one question"
    if len(questions) > MAX_QUESTIONS:
        return f"AskUserQuestion takes at most {MAX_QUESTIONS} questions"
    for index, question in enumerate(questions, start=1):
        if not str((question or {}).get("question") or "").strip():
            return f"question {index} needs its text"
        header = str(question.get("header") or "")
        if len(header) > MAX_HEADER_CHARS:
            return f"question {index} has a header over {MAX_HEADER_CHARS} characters"
        options = question.get("options") or []
        if not 2 <= len(options) <= MAX_OPTIONS:
            return f"question {index} needs between two and {MAX_OPTIONS} options"
    return ""


@tool(
    name="EnterPlanMode",
    description="Ask to switch this session into plan mode "
    "before starting anything but a trivial "
    "change. In plan mode nothing that writes or "
    "changes state runs, so you can explore and "
    "design the approach and have it approved "
    "before touching the project.",
    parameters={"type": "object", "properties": {}},
)
async def enter_plan_mode(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    if str(getattr(team.hooks, "permission_mode", "")) == "plan":
        return "Already in plan mode."
    team.set_plan_mode("plan")
    return ENTER_TEXT.format(path=plan_file(team))


@tool(
    name="ExitPlanMode",
    description="Present the plan you wrote to the user and leave plan mode once they approve it.",
    parameters={"type": "object", "properties": {}},
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
    description="Ask the human one to four questions and wait "
    "for the answers, when a choice they can make "
    "would change what you do. Give each question "
    "two to four options worth picking; they can "
    "also answer in their own words. When they "
    "have to compare concrete results, put the "
    "artifact on the option as preview.",
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "header": {"type": "string"},
                        "multiSelect": {"type": "boolean"},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                    "preview": {
                                        "type": "string",
                                        "description": "The artifact this option would produce, shown beside the options while it is picked. Use it when the user has to compare concrete results, not for a plain preference. Only single-select questions show previews.",
                                    },
                                },
                                "required": ["label"],
                            },
                        },
                    },
                    "required": ["question", "options"],
                },
            }
        },
        "required": ["questions"],
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
    description="Return your final answer as the structured "
    "payload below. Call it exactly once, at the "
    "end of the work; nothing you say in prose "
    "counts as the answer.\n\nThe payload must "
    "match this schema.",
    parameters=None,
)
async def structured_output(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    problem = mismatch(team.output_schema or {}, input)
    if problem:
        return f"Error: output does not match the required schema: {problem}"
    team.structured_output = dict(input)
    return "Structured output recorded. Finish the run now."


def _cron_where(task: dict) -> str:
    if task.get("durable") is False:
        return "Session-only (not written to disk, dies when pyclaw exits)"
    return "Persisted to scheduled_tasks.json"


def _cron_line(task: dict) -> str:
    kind = "recurring" if task.get("recurring") else "one-shot"
    marker = " [session-only]" if task.get("durable") is False else ""
    prompt = str(task.get("prompt") or "")
    if len(prompt) > 80:
        prompt = prompt[:80] + "…"
    return f"{task['id']} — {human(task['cron'])} ({kind}){marker}: {prompt}"


@tool(
    name="CronCreate",
    description="Schedule a prompt to be enqueued at a "
    "future time — recurring on a cron schedule, "
    "or once at a specific time. Standard "
    "5-field cron in local time: minute hour "
    "day-of-month month day-of-week. One-shot "
    "reminders (recurring: false) fire once at "
    "the next match then auto-delete — pin "
    "minute/hour/day-of-month/month, e.g. "
    '"30 14 27 5 *" for 2:30pm on May 27. Avoid '
    "the :00 and :30 minute marks when the user "
    'is approximate ("every morning around 9" -> '
    '"57 8 * * *"): everyone who asks for "9am" '
    "lands on the same wall-clock marks. "
    "Recurring jobs auto-expire after 7 days — "
    "tell the user about that limit. durable: "
    "true persists to scheduled_tasks.json so "
    "the job survives restarts; the default "
    "false keeps it session-only. Only use "
    "durable when the user explicitly asks the "
    "task to persist.",
    parameters={
        "type": "object",
        "properties": {
            "cron": {"type": "string"},
            "prompt": {"type": "string"},
            "recurring": {"type": "boolean"},
            "durable": {"type": "boolean"},
        },
        "required": ["cron", "prompt"],
    },
)
async def cron_create(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    task = team.cron.add(
        str(input.get("cron") or ""),
        str(input.get("prompt") or ""),
        recurring=bool(input.get("recurring", True)),
        durable=bool(input.get("durable")),
    )
    if task is None:
        return f"Error: {team.cron.refused}"
    if task.get("recurring"):
        return (
            f"Scheduled recurring job {task['id']} "
            f"({human(task['cron'])}). {_cron_where(task)}. "
            f"Auto-expires after 7 days. Use CronDelete to cancel "
            f"sooner."
        )
    return (
        f"Scheduled one-shot task {task['id']} "
        f"({human(task['cron'])}). {_cron_where(task)}. "
        f"It will fire once then auto-delete."
    )


@tool(
    name="CronList",
    description="Show every scheduled prompt with its id, schedule and whether it is durable.",
    parameters={"type": "object", "properties": {}},
)
async def cron_list(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    tasks = team.cron.all()
    if not tasks:
        return "Nothing scheduled."
    return "\n".join(_cron_line(task) for task in tasks)


@tool(
    name="CronDelete",
    description="Cancel a scheduled prompt by its id.",
    parameters={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
)
async def cron_delete(context, team, agent, input: dict, tool_use_id: str = "") -> str:
    ident = str(input.get("id") or "").strip()
    removed = team.cron.remove(ident)
    if removed is None:
        return f'Error: nothing scheduled under "{ident}"'
    return f"{removed['id']} cancelled."


def team_tools(team) -> list[Tool]:
    """The Tool instances available to this team, one list per capability."""
    tools = [create_agent.with_description(team._create_agent_description())]
    if team.multi_agent:
        tools += [send_message, task_output, task_stop, team_create, team_delete]
    if team.tasks is not None:
        tools += [task_create, task_list, task_get, task_update]
    if team.skills.for_model():
        listing = team.skills.listing(listing_budget(team.context_window))
        tools.append(
            use_skill.with_description(
                "Load the full instructions of one skill when the task at hand "
                "is one it covers. The listing below only says what each skill "
                "is for; the steps come from this call.\n\nAvailable skills:\n" + listing
            )
        )
    if team.can_worktree:
        tools += [enter_worktree, exit_worktree]
    if team.ask_user is not None:
        tools += [ask_user, enter_plan_mode, exit_plan_mode]
    if team.cron is not None:
        tools += [cron_create, cron_list, cron_delete]
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
