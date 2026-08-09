from __future__ import annotations

from chatchat.agent import AgentConfig
from chatchat.message import Message, make_id
from chatchat.tool import tool, Tool


def create_agent_tool(agent, agent_tools=None) -> Tool:
    @tool(
        name='create_agent',
        description='Create a sub-agent for delegated tasks. Use this when a task is independent enough to run separately, or when you need parallel work.',
        parameters={
            'type': 'object',
            'properties': {
                'instruction': {'type': 'string', 'description': 'Task description for the sub-agent'},
            },
            'required': ['instruction'],
        },
    )
    def _(instruction: str) -> str:
        agent_id = make_id()
        if agent_id in agent._sub_agents:
            return f'error: agent "{agent_id}" already exists'
        cfg = AgentConfig(
            name=agent_id, instruction=instruction,
            provider=agent.config.provider, model=agent.config.model,
            stream=True, thinking=agent.config.thinking,
            http_options=agent.config.http_options,
            max_turns=agent.config.max_turns,
            source='user', tools=agent_tools,
        )
        sub = agent.create_sub_agent(cfg)
        sub.add_tool(send_message_tool(sub))
        result = sub.chat(instruction)
        return f'[Agent "{agent_id}" completed]\n{result}'
    return _


def send_message_tool(agent) -> Tool:
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
    def _(to: str, message: str, blocking: bool = False) -> str:
        target = agent.scheduler.lookup_by_name(to)
        if not target:
            return f'error: unknown agent "{to}"'
        msg = Message(
            sender=agent.id, recipient=target.id,
            type='text', payload=message,
        )
        if blocking:
            try:
                reply = agent.scheduler.request(msg, timeout=60)
                return f'reply from {to}: {reply.payload}'
            except Exception as e:
                return f'error waiting for reply: {e}'
        agent.scheduler.send(msg)
        return f'message sent to {to}'
    return _


def task_stop_tool(agent) -> Tool:
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
    def _(name: str) -> str:
        if name not in agent._sub_agents:
            return f'error: unknown sub-agent "{name}"'
        sub = agent._sub_agents[name]
        sub.stop()
        agent.scheduler.unregister(sub.id)
        del agent._sub_agents[name]
        return f'agent "{name}" stopped'
    return _