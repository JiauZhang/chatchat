from __future__ import annotations

from chatchat.core.event import Event
from chatchat.core.ids import make_id
from chatchat.tools.base import ToolContext, tool
from chatchat.tools.registry import ToolRegistry


def ensure_builtin_tools(registry: ToolRegistry):
    for t in (create_agent_tool, create_team_tool, send_message_tool, task_stop_tool):
        if registry.resolve(t.name) is None:
            registry.register(t)


@tool(
    name='create_agent',
    description='Create a sub-agent. The instruction is its system role and rulebook — define who it is and its boundaries, NOT a task; tasks go later via send_message(<id>, <task>). Returns the id of the newly created sub-agent.',
    parameters={
        'type': 'object',
        'properties': {
            'instruction': {'type': 'string', 'description': 'System role and constraints for the new sub-agent: who it is and how it should behave. Do NOT put a concrete task here.'},
        },
        'required': ['instruction'],
    },
)
async def create_agent_tool(ctx: ToolContext, instruction: str) -> str:
    from chatchat.agents.agent import AgentConfig, create_agent
    team = ctx.agent
    tools = list(team.agent_tools or []) + ['send_message']
    cfg = AgentConfig(**{
        f: getattr(team.config, f)
        for f in ('provider', 'model', 'thinking', 'http_options', 'max_steps', 'max_depth', 'background', 'description', 'skills')
    }, instruction=instruction, tools=tools, source='user')
    sub = team.create_sub_agent(cfg)
    # Sub-agent starts idle, driven only by its system instruction. The caller
    # holds its id and dispatches concrete tasks later via send_message.
    return f'new agent created, its id is {sub.id}'


@tool(
    name='create_team',
    description='Create a sub-team: a new leader entity that can itself create and orchestrate more entities. The instruction is the sub-team leader system role and rulebook — define who it is and its boundaries, NOT a task; tasks go later via send_message(<id>, <task>). Returns the id of the newly created sub-team.',
    parameters={
        'type': 'object',
        'properties': {
            'instruction': {'type': 'string', 'description': 'System role and constraints for the sub-team leader: who it is and how it should behave. Do NOT put a concrete task here.'},
        },
        'required': ['instruction'],
    },
)
async def create_team_tool(ctx: ToolContext, instruction: str) -> str:
    from chatchat.agents.agent import BaseAgentConfig
    from chatchat.agents.team import TeamConfig
    team = ctx.agent
    data = {f: getattr(team.config, f)
            for f in BaseAgentConfig.__dataclass_fields__ if f != 'id'}
    data.update(id=make_id(), instruction=instruction,
                leader_tools=None, agent_tools=team.agent_tools, source='user')
    cfg = TeamConfig(**data)
    sub_team = team.create_sub_team(cfg)
    return f'new team created, its id is {sub_team.id}'


@tool(
    name='send_message',
    description='Send a message to another entity by its id. This is the only way to communicate. Set expect_reply=True when you need the answer: it arrives later as a notification, not in the return value — after sending, do NOT send again or repeat the same task; rely on the reply. expect_reply=False is one-way (no answer will come).',
    parameters={
        'type': 'object',
        'properties': {
            'to': {'type': 'string', 'description': 'Target entity id'},
            'message': {'type': 'string', 'description': 'Message content'},
            'expect_reply': {'type': 'boolean', 'description': 'Whether a reply is required. Omit nothing: you must decide True or False'},
        },
        'required': ['to', 'message', 'expect_reply'],
    },
)
async def send_message_tool(ctx: ToolContext, to: str, message: str, expect_reply: bool) -> str:
    return await _send_one(ctx.agent, to, message, expect_reply)


async def _send_one(agent, to_id: str, message: str, expect_reply: bool) -> str:
    import time
    entry = agent._runtime.lookup_entity(to_id)
    if not entry:
        return f'error: unknown agent id "{to_id}"'
    if expect_reply:
        now = time.time()
        deadline = now + getattr(agent._runtime, 'reply_ttl', 120.0)
        count, _ = agent._pending_reply.get(to_id, (0, 0.0))
        agent._pending_reply[to_id] = (count + 1, deadline)
    kind = entry[0]
    await agent._runtime.publish(Event(
        topic=f'entity:{kind}:{to_id}:text',
        source=agent.id, data=message, expect_reply=expect_reply,
    ))
    return f'message sent to {to_id}; {to_id} will reply once done'


@tool(
    name='task_stop',
    description='Permanently stop your sub-entity by its id and release it. Use only to retire a failed, stuck, or no-longer-needed sub-entity. Nothing stops itself or non-sub entities.',
    parameters={
        'type': 'object',
        'properties': {
            'agent_id': {'type': 'string', 'description': 'Id of your sub-entity (agent or team) to stop'},
        },
        'required': ['agent_id'],
    },
)
async def task_stop_tool(ctx: ToolContext, agent_id: str) -> str:
    agent = ctx.agent
    sub = agent._sub_agents.get(agent_id)
    if not sub:
        return f'error: unknown sub-agent id "{agent_id}"'
    await sub.stop()
    agent._runtime.unregister_entity(sub.id)
    del agent._sub_agents[agent_id]
    return f'agent {agent_id} stopped'