from __future__ import annotations

from chatchat.team.agents import resolve_agent_model
from chatchat.tool import Tool, tool


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


def tools(team) -> list[Tool]:
    return [use_skill] if team.skills.all() else []
