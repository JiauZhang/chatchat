from __future__ import annotations

from chatchat.agent import AgentConfig, create_agent
from chatchat.runtime import Event, make_id
from chatchat.tool import ToolContext, tool


@tool(
    name='create_agent',
    description='Create a sub-agent for delegated tasks. Use this when a task is independent enough to run separately, or when you need parallel work. The sub-agent runs on its own and reports back via notification; do not expect an immediate reply.',
    parameters={
        'type': 'object',
        'properties': {
            'instruction': {'type': 'string', 'description': 'Task description for the sub-agent'},
        },
        'required': ['instruction'],
    },
)
async def create_agent_tool(ctx: ToolContext, instruction: str) -> str:
    team = ctx.agent
    agent_id = make_id()
    tools = list(team.agent_tools or []) + ['send_message']
    cfg = AgentConfig(**{
        f: getattr(team.config, f)
        for f in ('provider', 'model', 'thinking', 'http_options', 'max_steps', 'max_depth', 'background', 'description', 'skills')
    }, name=agent_id, instruction=instruction, tools=tools, source='user')
    sub = team.create_sub_agent(cfg)
    # Fire-and-forget: publish the task; the sub-agent's result returns via
    # notification, consumed by the leader on its next _drain_notifications.
    await team._runtime.publish(Event(
        topic=f'entity:{sub.kind}:{sub.id}:text',
        source=team.id, data=instruction,
    ))
    return f'[Agent "{agent_id}" spawned; it will report back when done]'


@tool(
    name='send_message',
    description='Send a message to a sub-agent. Replies come back as notifications (consume via your notifications), not as a return value.',
    parameters={
        'type': 'object',
        'properties': {
            'to': {'type': 'string', 'description': 'Target agent name (omit when broadcasting)'},
            'message': {'type': 'string', 'description': 'Message content'},
            'broadcast': {'type': 'boolean', 'description': 'Send to all sub-agents; ignored if "to" is set'},
        },
        'required': ['message'],
    },
)
async def send_message_tool(ctx: ToolContext, message: str, to: str = '', broadcast: bool = False) -> str:
    agent = ctx.agent
    if not to and not broadcast:
        return 'error: provide "to" or set broadcast=true'
    if to:
        return await _send_one(agent, to, message)
    count = 0
    for name in list(agent._sub_agents.keys()):
        await _send_one(agent, name, message)
        count += 1
    return f'message broadcast to {count} sub-agent(s)'


async def _send_one(agent, to: str, message: str) -> str:
    target_id, entry = agent._runtime.lookup(to)
    if not entry:
        return f'error: unknown agent "{to}"'
    kind = entry[0]
    await agent._runtime.publish(Event(
        topic=f'entity:{kind}:{target_id}:text',
        source=agent.id, data=message,
    ))
    return f'message sent to {to}'


@tool(
    name='task_stop',
    description='Stop a running sub-agent.',
    parameters={
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'description': 'Name of the sub-agent to stop'},
        },
        'required': ['name'],
    },
)
async def task_stop_tool(ctx: ToolContext, name: str) -> str:
    agent = ctx.agent
    if name not in agent._sub_agents:
        return f'error: unknown sub-agent "{name}"'
    sub = agent._sub_agents[name]
    await sub.stop()
    agent._runtime.unregister_entity(sub.id)
    del agent._sub_agents[name]
    return f'agent "{name}" stopped'
