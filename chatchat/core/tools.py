from __future__ import annotations

from chatchat.core.tasks import TASK_STATUSES
from chatchat.hooks.output import describe_blocking


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
                agent, 'message', message, f'{agent.name} -> *')
        names = ', '.join(r.name for r in recipients)
        return (f'Told {len(recipients)} teammate(s): {names}. {note}')
    recipient = team.get_by_name(to)
    if recipient is None:
        return f'Error: unknown teammate "{to}"'
    recipient.inbox.write(agent.name, message)
    if agent is not None and not agent._internal:
        await team.hooks.execute_notification_hooks(
            agent, 'message', message, f'{agent.name} -> {to}')
    return (f"Sent to {to}, who reads it on their next idle turn. {note}")


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
        created = await team.hooks.execute_task_created_hooks(
            agent, f'{agent.name}:sub', prompt)
        if created.blocking_error is not None:
            return f'Error: {describe_blocking(created.blocking_error)}'
    result = await team.spawn_subagent(
        prompt, subagent_type=input.get('subagent_type'),
        instruction=cfg, model=input.get('model'),
        depth=getattr(agent, 'depth', 0) + 1,
        tool_use_id=tool_use_id)
    if agent is not None and not agent._internal:
        done = await team.hooks.execute_task_completed_hooks(
            agent, f'{agent.name}:sub', prompt)
        if done.blocking_error is not None:
            return f'{result}\n{describe_blocking(done.blocking_error)}'
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


def _open_blockers(tasks, task) -> list[str]:
    unresolved = {t.id for t in tasks if t.open()}
    return [b for b in task.blocked_by if b in unresolved]


async def task_create(team, agent, input: dict, tool_use_id: str = '') -> str:
    subject = str(input.get('subject') or '').strip()
    description = str(input.get('description') or '').strip()
    if not subject or not description:
        return 'Error: task_create needs both subject and description'
    task = team.tasks.create(subject, description,
                             active_form=str(input.get('active_form') or ''),
                             metadata=input.get('metadata') or {})
    return f'Task #{task.id} created: {task.subject}'


async def task_list(team, agent, input: dict, tool_use_id: str = '') -> str:
    tasks = team.tasks.all()
    if not tasks:
        return 'No tasks yet'
    lines = []
    for task in tasks:
        blockers = _open_blockers(tasks, task)
        lines.append(f'#{task.id} [{task.status}] {task.subject}'
                     + (f' ({task.owner})' if task.owner else '')
                     + (' [blocked by '
                        + ', '.join(f'#{b}' for b in blockers) + ']'
                        if blockers else ''))
    return '\n'.join(lines)


async def task_get(team, agent, input: dict, tool_use_id: str = '') -> str:
    task = team.tasks.get(input.get('task_id') or '')
    if task is None:
        return 'Error: task not found'
    lines = [f'Task #{task.id}: {task.subject}', f'Status: {task.status}',
             f'Description: {task.description}']
    if task.owner:
        lines.append(f'Owner: {task.owner}')
    if task.blocked_by:
        lines.append('Blocked by: '
                     + ', '.join(f'#{b}' for b in task.blocked_by))
    if task.blocks:
        lines.append('Blocks: ' + ', '.join(f'#{b}' for b in task.blocks))
    return '\n'.join(lines)


async def task_update(team, agent, input: dict, tool_use_id: str = '') -> str:
    task_id = input.get('task_id')
    if not task_id:
        return 'Error: task_update needs a task_id'
    if input.get('status') == 'deleted':
        return (f'Task #{task_id} deleted' if team.tasks.delete(task_id)
                else 'Error: task not found')
    fields = {key: input[key] for key in
              ('subject', 'description', 'active_form', 'status', 'owner',
               'metadata') if input.get(key) is not None}
    parts = [f'{key} -> {value}' if key == 'status' else key
             for key, value in fields.items()]
    for key, forward in (('add_blocks', True), ('add_blocked_by', False)):
        wanted = input.get(key) or []
        linked = 0
        for other in wanted:
            ok = (team.tasks.block(task_id, other) if forward
                  else team.tasks.block(other, task_id))
            if not ok:
                return f'Error: task #{other} does not exist to link'
            linked += 1
        if linked:
            parts.append(key)
    if not parts:
        return 'Error: task_update was given nothing to change'
    if fields and team.tasks.update(task_id, **fields) is None:
        return ('Error: status must be one of '
                f'{", ".join(TASK_STATUSES)}, or "deleted" to remove the task')
    return f'Task #{task_id} updated: ' + ', '.join(parts)


async def use_skill(team, agent, input: dict, tool_use_id: str = '') -> str:
    name = str(input.get('skill') or '').strip()
    if not name:
        return 'Error: use_skill needs the skill name'
    registry = team.skills
    skill = registry.get(name)
    if skill is None:
        available = ', '.join(other.name for other in registry.all())
        return (f'Error: no such skill: {name}. Available: '
                f'{available or "none"}')
    args = str(input.get('args') or '').strip()
    return skill.render(args)
