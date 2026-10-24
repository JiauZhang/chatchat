from __future__ import annotations

import asyncio

from chatchat.hooks.output import describe_blocking
from chatchat.tool import Tool, tool

TASK_DEFAULT_TIMEOUT_MS = 30_000
TASK_MAX_TIMEOUT_MS = 600_000

SUBAGENT_INSTRUCTION = "You are an autonomous sub-agent. Complete the task and give your final answer."

AGENT_DESCRIPTION = """Run a sub-agent on one task and return its final answer.
Without a name it is a one-off sub-agent: it runs synchronously, answers, then is reclaimed.
With a name it becomes a persistent teammate that keeps a mailbox, so assign it work with SendMessage.
subagent_type picks its AgentDefinition; general-purpose is the default."""


def _described(team) -> str:
    lines = [f"- {agent_type}: {when_to_use}" for agent_type, when_to_use in team.agent_defs.describe()]
    if not lines:
        return AGENT_DESCRIPTION
    return AGENT_DESCRIPTION + "\nAvailable subagent types:\n" + "\n".join(lines)


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


def tools(team) -> list[Tool]:
    found = [create_agent.with_description(_described(team))]
    if team.multi_agent:
        found += [task_output, task_stop]
    return found
