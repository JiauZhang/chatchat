from __future__ import annotations

import inspect

from chatchat.core.cron_schedule import describe as describe_task
from chatchat.core.plan import (APPROVE, AUTO_ACCEPT, ENTER_TEXT,
                                plan_file, plan_question, read_plan)
from chatchat.core.tasks import TASK_STATUSES
from chatchat.core.structured import mismatch
from chatchat.hooks.output import describe_blocking


async def send_message(team, agent, input: dict, tool_use_id: str = '') -> str:
    to = input.get('to', '')
    message = input.get('message', '') or ''
    note = ('Do NOT re-send or poll them; wait for their teammate-message back.')
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
    background = bool(input.get('run_in_background'))
    if background and name:
        return ('Error: a named teammate already works in the background; '
                'run_in_background is for a one-off sub-agent.')
    if background and agent is not None and agent._internal:
        return ('Error: only the agent that owns the conversation can send '
                'work to the background. Finish your own sub-agent here.')
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
                f'SendMessage (to: "{name}"); stop it with TaskStop '
                f'(agent_id: {teammate.agent_id}).')
    if background:
        agent_id = await team.spawn_background_subagent(
            prompt, agent or team.lead,
            subagent_type=input.get('subagent_type'), instruction=cfg,
            model=input.get('model'), depth=getattr(agent, 'depth', 0) + 1,
            tool_use_id=tool_use_id)
        return (f'{agent_id.rsplit("@", 1)[0]} is running in the background. '
                f'Do not wait for it; its answer arrives in your inbox when '
                f'it is done (agent_id: {agent_id}; stop it with TaskStop).')
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


async def task_stop(team, agent, input: dict,
                    tool_use_id: str = '') -> str | None:
    target = str(input.get('task_id') or '').strip()
    if not target:
        return 'Error: TaskStop needs a task_id'
    agent_id = target if '@' in target else team.agent_id(target)
    if agent_id not in team.agents:
        return None
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
        return 'Error: TaskCreate needs both subject and description'
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
        return 'Error: TaskUpdate needs a task_id'
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
        return 'Error: TaskUpdate was given nothing to change'
    if fields and team.tasks.update(task_id, **fields) is None:
        return ('Error: status must be one of '
                f'{", ".join(TASK_STATUSES)}, or "deleted" to remove the task')
    return f'Task #{task_id} updated: ' + ', '.join(parts)


async def use_skill(team, agent, input: dict, tool_use_id: str = '') -> str:
    name = str(input.get('skill') or '').strip()
    if not name:
        return 'Error: Skill needs the name of the skill'
    registry = team.skills
    skill = registry.get(name)
    if skill is None:
        available = ', '.join(other.name for other in registry.all())
        return (f'Error: no such skill: {name}. Available: '
                f'{available or "none"}')
    args = str(input.get('args') or '').strip()
    return skill.render(args)


async def team_create(team, agent, input: dict, tool_use_id: str = '') -> str:
    name = str(input.get('team_name') or '').strip()
    if not name:
        return 'Error: TeamCreate needs a team_name'
    try:
        team.join_team(name, str(input.get('description') or '').strip())
    except ValueError as exc:
        return f'Error: {exc}'
    return (f'Team "{name}" is active. Its task list is the team: everything '
            f'you add with TaskCreate is shared with the teammates you spawn '
            f'from now on.')


async def team_delete(team, agent, input: dict, tool_use_id: str = '') -> str:
    try:
        team.leave_team()
    except ValueError as exc:
        return f'Error: {exc}'
    return 'Cleaned up the team record and its task list.'


async def enter_worktree(team, agent, input: dict,
                         tool_use_id: str = '') -> str:
    try:
        return await team.enter_worktree(str(input.get('name') or ''))
    except ValueError as exc:
        return f'Error: {exc}'


async def exit_worktree(team, agent, input: dict, tool_use_id: str = '') -> str:
    return await team.exit_worktree(keep=str(input.get('action') or '')
                                   == 'keep')


MAX_QUESTIONS = 4
MAX_OPTIONS = 4
MAX_HEADER_CHARS = 12


def _question_problems(questions) -> str:
    if not isinstance(questions, list) or not questions:
        return 'AskUserQuestion needs at least one question'
    if len(questions) > MAX_QUESTIONS:
        return f'AskUserQuestion takes at most {MAX_QUESTIONS} questions'
    for index, question in enumerate(questions, start=1):
        if not str((question or {}).get('question') or '').strip():
            return f'question {index} needs its text'
        header = str(question.get('header') or '')
        if len(header) > MAX_HEADER_CHARS:
            return (f'question {index} has a header over '
                    f'{MAX_HEADER_CHARS} characters')
        options = question.get('options') or []
        if not 2 <= len(options) <= MAX_OPTIONS:
            return f'question {index} needs between two and {MAX_OPTIONS} options'
    return ''


async def enter_plan_mode(team, agent, input: dict,
                          tool_use_id: str = '') -> str:
    if str(getattr(team.hooks, 'permission_mode', '')) == 'plan':
        return 'Already in plan mode.'
    team.set_plan_mode('plan')
    return ENTER_TEXT.format(path=plan_file(team))


async def exit_plan_mode(team, agent, input: dict,
                         tool_use_id: str = '') -> str:
    plan = read_plan(team)
    if not plan:
        return f'Error: nothing has been written to {plan_file(team)} yet.'
    if team.ask_user is None:
        return 'Error: no one can approve a plan in this session.'
    answers = team.ask_user(agent, [plan_question()])
    if inspect.isawaitable(answers):
        answers = await answers
    choice = str(answers[0] if answers else '')
    if choice == AUTO_ACCEPT:
        team.set_plan_mode('acceptEdits')
        return ('The user approved the plan and wants the edits applied '
                f'without further prompts.\n\n{plan}')
    if choice == APPROVE:
        team.set_plan_mode('default')
        return f'The user approved the plan.\n\n{plan}'
    return ('The user did not approve the plan. Stay in plan mode and ask '
            'what they want changed.')


async def ask_user(team, agent, input: dict, tool_use_id: str = '') -> str:
    import asyncio as _asyncio

    questions = input.get('questions') or []
    problem = _question_problems(questions)
    if problem:
        return f'Error: {problem}'
    await team.hooks.execute_elicitation_hooks(
        agent, str(questions[0].get('question') or ''))
    answers = team.ask_user(agent, questions)
    if _asyncio.iscoroutine(answers):
        answers = await answers
    lines = []
    for index, question in enumerate(questions):
        answer = str(answers[index] if index < len(answers) else '')
        answer = answer or 'no answer'
        lines.append(f'{question["question"]}: {answer}')
    await team.hooks.execute_elicitation_result_hooks(
        agent, '\n'.join(lines))
    return ('The user answered:\n' + '\n'.join(lines)
            + '\nCarry on with those answers.')


async def structured_output(team, agent, input: dict,
                            tool_use_id: str = '') -> str:
    problem = mismatch(team.output_schema or {}, input)
    if problem:
        return f'Error: output does not match the required schema: {problem}'
    team.structured_output = dict(input)
    return 'Structured output recorded. Finish the run now.'


async def cron_create(team, agent, input: dict, tool_use_id: str = '') -> str:
    task = team.cron.add(str(input.get('cron') or ''),
                         str(input.get('prompt') or ''),
                         recurring=bool(input.get('recurring', True)),
                         durable=bool(input.get('durable')))
    if task is None:
        return f'Error: {team.cron.refused}'
    return f'Scheduled {task["id"]}: {describe_task(task)}'


async def cron_list(team, agent, input: dict, tool_use_id: str = '') -> str:
    tasks = team.cron.all()
    if not tasks:
        return 'Nothing scheduled.'
    return 'Scheduled prompts:\n' + '\n'.join(
        f'- {describe_task(task)}' for task in tasks)


async def cron_delete(team, agent, input: dict, tool_use_id: str = '') -> str:
    ident = str(input.get('id') or '').strip()
    removed = team.cron.remove(ident)
    if removed is None:
        return f'Error: nothing scheduled under "{ident}"'
    return f'{removed["id"]} cancelled.'
