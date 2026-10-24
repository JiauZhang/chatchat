from __future__ import annotations

from chatchat.tool import Tool, tool


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


def tools(team) -> list[Tool]:
    return [send_message] if team.multi_agent else []
