from __future__ import annotations
from typing import TYPE_CHECKING

from chatchat.message import Message
from chatchat.tool import Tool

if TYPE_CHECKING:
    from chatchat.agent import Agent, AgentConfig


def create_agent_tool(agent: Agent) -> Tool:
    def _create_agent(name: str, instruction: str, description: str = '',
                      background: bool = False, provider: str = None,
                      model: str = None) -> str:
        if name in agent._sub_agents:
            return f'error: agent "{name}" already exists'
        from chatchat.agent import AgentConfig, create_agent as do_create
        cfg = AgentConfig(
            name=name, description=description, instruction=instruction,
            provider=provider or agent.config.provider,
            model=model or agent.config.model,
            stream=True, thinking=agent.config.thinking,
            http_options=agent.config.http_options,
            max_turns=agent.config.max_turns,
            background=background, source='user',
        )
        sub = agent.create_sub_agent(cfg)
        if background:
            sub.start()
            agent.scheduler.send(Message(
                sender=agent.id, recipient=sub.id,
                type='text', payload=instruction,
            ))
            return f'Agent "{name}" started in background. You will be notified when it completes.'
        result = sub.chat(instruction)
        return f'[Agent "{name}" completed]\n{result}'

    return Tool(
        name='create_agent',
        description=(
            'Create a sub-agent for delegated tasks. Use this when a task is independent '
            'enough to run separately, or when you need parallel work. For foreground '
            '(default), the result is returned immediately. For background, the agent runs '
            'asynchronously and you will be notified when it completes.'
        ),
        tool=_create_agent,
        parameters={
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Name for the sub-agent'},
                'instruction': {'type': 'string', 'description': 'System prompt and task description for the sub-agent'},
                'description': {'type': 'string', 'description': 'Brief description of what this sub-agent will do'},
                'background': {'type': 'boolean', 'description': 'Run in background (default false). When true, the agent runs asynchronously and notifies you when complete.'},
                'provider': {'type': 'string', 'description': 'Optional provider override'},
                'model': {'type': 'string', 'description': 'Optional model override'},
            },
            'required': ['name', 'instruction'],
        },
    )


def send_message_tool(agent: Agent) -> Tool:
    def _send_message(to: str, message: str, blocking: bool = False) -> str:
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

    return Tool(
        name='send_message',
        description=(
            'Send a message to a sub-agent and optionally wait for reply. Use this to '
            'continue a sub-agent with additional context or instructions.'
        ),
        tool=_send_message,
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


def task_stop_tool(agent: Agent) -> Tool:
    def _task_stop(name: str) -> str:
        if name not in agent._sub_agents:
            return f'error: unknown sub-agent "{name}"'
        sub = agent._sub_agents[name]
        sub.stop()
        agent.scheduler.unregister(sub.id)
        del agent._sub_agents[name]
        return f'agent "{name}" stopped'

    return Tool(
        name='task_stop',
        description=(
            'Stop a running sub-agent. Use this when a sub-agent is no longer needed '
            'or is going in the wrong direction.'
        ),
        tool=_task_stop,
        parameters={
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Name of the sub-agent to stop'},
            },
            'required': ['name'],
        },
    )