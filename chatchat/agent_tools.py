from __future__ import annotations

from chatchat.exceptions import SubAgentError
from chatchat.runtime import Event
from chatchat.tool import tool, ToolContext


async def delegate_task(agent, target, message: str, timeout: float = 300):
    try:
        reply = await agent._runtime.request(
            source=agent.id, target_id=target.id,
            topic=f'entity:{target.kind}:{target.id}:text',
            data=message, timeout=timeout,
        )
    except SubAgentError:
        raise
    except Exception as e:
        raise SubAgentError(f'{target.kind} "{target.id}" failed: {e}') from e
    if isinstance(reply, Exception):
        raise SubAgentError(f'{target.kind} "{target.id}" failed: {reply}') from reply
    return reply


@tool(
    name='send_message',
    description='Send a message to a sub-agent and optionally wait for reply.',
    parameters={
        'type': 'object',
        'properties': {
            'to': {'type': 'string', 'description': 'Target agent name'},
            'message': {'type': 'string', 'description': 'Message content'},
            'blocking': {'type': 'boolean', 'description': 'Wait for reply (default false)'},
        },
        'required': ['to', 'message'],
    },
)
async def send_message_tool(ctx: ToolContext, to: str, message: str, blocking: bool = False) -> str:
    agent = ctx.agent
    target_id, entry = agent._runtime.lookup(to)
    if not entry:
        return f'error: unknown agent "{to}"'
    kind = entry[0]
    topic = f'entity:{kind}:{target_id}:text'
    if blocking:
        try:
            reply = await agent._runtime.request(
                source=agent.id, target_id=target_id, topic=topic, data=message, timeout=60,
            )
        except Exception as e:
            return f'error waiting for reply: {e}'
        if isinstance(reply, Exception):
            return f'error from {to}: {reply}'
        return f'reply from {to}: {reply}'
    await agent._runtime.publish(Event(topic=topic, source=agent.id, data=message))
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