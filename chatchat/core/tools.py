from __future__ import annotations


async def send_message(team, agent, input: dict, tool_use_id: str = '') -> str:
    to = input.get('to', '')
    message = input.get('message', '') or ''
    note = ('Do NOT re-send or poll them; wait for their teammate_message back.')
    if to == '*':
        recipients = [a for a in team.agents.values() if a.name != agent.name]
        if not recipients:
            return 'No teammates to broadcast to (you are the only agent)'
        for r in recipients:
            r.inbox.write(agent.name, message)
        if agent is not None and not agent._internal:
            await team.hooks.execute_notification_hooks(
                agent, 'message', '*',
                [{'teammate_id': r.name, 'message': message}
                 for r in recipients])
        names = ', '.join(r.name for r in recipients)
        return (f'Message broadcast to {len(recipients)} teammate(s): '
                f'{names}. {note}')
    recipient = team.get_by_name(to)
    if recipient is None:
        return f'Error: unknown teammate "{to}"'
    recipient.inbox.write(agent.name, message)
    if agent is not None and not agent._internal:
        await team.hooks.execute_notification_hooks(
            agent, 'message', to, [{'teammate_id': to, 'message': message}])
    return (f"Message delivered to {to}'s inbox; they'll read it on their "
            f'next idle turn. {note}')


async def create_agent(team, agent, input: dict, tool_use_id: str = '') -> str:
    prompt = input.get('prompt', '')
    cfg = input.get('instruction') or (
        'You are an autonomous sub-agent. Complete the task and give your '
        'final answer.')
    name = input.get('name')
    if name and getattr(team, 'multi_agent', True):
        if agent is not None and not agent.ctx.leader:
            return ('Error: Teammates cannot spawn other teammates — '
                    'the team roster is flat.')
        teammate = team.create_agent(
            str(name), instruction=cfg, model=input.get('model'),
            depth=getattr(agent, 'depth', 0) + 1)
        team.parents[teammate.agent_id] = agent.agent_id
        team.children.setdefault(agent.agent_id, set()).add(teammate.agent_id)
        teammate.submit(prompt)
        return (f'Teammate "{name}" spawned and idle. Assign work with '
                f'send_message (to: "{name}"); stop it with task_stop '
                f'(agent_id: {teammate.agent_id}).')
    if agent is not None and not agent._internal:
        await team.hooks.execute_task_created_hooks(
            agent, f'{agent.name}:sub', '', agent.name)
    try:
        result = await team.spawn_subagent(
            prompt, subagent_type=input.get('subagent_type'),
            instruction=cfg, model=input.get('model'),
            depth=getattr(agent, 'depth', 0) + 1,
            tool_use_id=tool_use_id)
    except Exception:
        if agent is not None and not agent._internal:
            await team.hooks.execute_task_completed_hooks(
                agent, f'{agent.name}:sub', 'error')
        raise
    if agent is not None and not agent._internal:
        await team.hooks.execute_task_completed_hooks(
            agent, f'{agent.name}:sub', 'completed')
    return result


async def task_stop(team, agent, input: dict, tool_use_id: str = '') -> str:
    target = input.get('agent_id') or input.get('name')
    if target is None:
        return 'Error: no agent_id given'
    agent_id = target if '@' in str(target) else team.agent_id(str(target))
    if agent_id not in team.children.get(agent.agent_id, set()):
        return f'Error: "{target}" is not your sub-agent'
    sub = team.agents.get(agent_id)
    if sub is not None:
        await team.stop_agent(sub)
    return f'agent {agent_id} stopped'
