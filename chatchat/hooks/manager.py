import asyncio
import os
import time
import uuid

from chatchat.core.thinking import Thinking
from chatchat.hooks.events import (AGENT_WARN, emit, emit_response,
                                emit_started)
from chatchat.hooks.executors import (EVALUATOR_INSTRUCTION, exec_agent_hook,
                                      exec_callback_hook, exec_command_hook,
                                      exec_function_hook, exec_http_hook,
                                      exec_prompt_hook)
from chatchat.hooks.matchers import if_condition_applies, if_matches, \
    matches_pattern
from chatchat.hooks.output import aggregate_results
from chatchat.hooks.schemas import (DEFAULT_TIMEOUTS, AggregatedHookResult,
                                    HookCommand, HookResult,
                                    IndividualHookConfig, get_hook_display_text)
from chatchat.hooks.settings import dedupe_hooks, get_all_hooks, \
    get_builtin_hooks

DEFAULT_PARENT = 'team-lead'


def _hook_detail(config) -> str:
    if config.type == 'command':
        return config.command or ''
    if config.type == 'http':
        return config.url or ''
    if config.type in ('prompt', 'agent'):
        return (config.prompt or '')[:80]
    return ''


def build_hook_input(event: str, *, session_id: str, agent=None, cwd: str = '',
                     permission_mode: str = '', **fields) -> dict:
    hook_input = {
        'session_id': session_id,
        'transcript_path': '',
        'cwd': cwd,
        'agent_id': agent.name if agent else None,
        'agent_type': (getattr(agent, 'agent_type', '')
                       or ('subagent' if getattr(agent, '_internal', False)
                           else None)
                       if agent else None),
        'hook_event_name': event,
    }
    if permission_mode:
        hook_input['permission_mode'] = permission_mode
    hook_input.update(fields)
    return hook_input


def _last_assistant_text(messages: list) -> str:
    for m in reversed(messages):
        if (isinstance(m, dict) and m.get('role') == 'assistant'
                and isinstance(m.get('content'), str)):
            return m['content']
    return ''


class HookManager:
    def __init__(self, team, enabled: bool = True):
        self._team = team
        self.enabled = enabled
        self._cwd = os.getcwd()
        self._session_id = uuid.uuid4().hex
        self.permission_mode = ''
        self._session_hooks: dict[str, list] = {}
        self._settings_hooks = None
        self._consumed_once: set[str] = set()
        self._counter = 0
        self._background_tasks: dict[str, asyncio.Task] = {}

    def register(self, event: str, matcher: str = '*', **kw) -> str:
        htype = kw.pop('type', None)
        fn = kw.get('fn')
        if htype is None:
            if fn is not None:
                htype = 'function'
            elif kw.get('command'):
                htype = 'command'
            elif kw.get('url'):
                htype = 'http'
            elif kw.get('prompt'):
                htype = 'prompt'
            else:
                raise ValueError('hook needs fn/command/prompt/url')
        allowed = {'command', 'prompt', 'url', 'if_', 'shell', 'timeout',
                   'status_message', 'once', 'async_', 'async_rewake',
                   'model', 'headers', 'allowed_env_vars', 'fn',
                   'error_message', 'internal'}
        config = HookCommand(type=htype, **{k: v for k, v in kw.items()
                                            if k in allowed})
        self._counter += 1
        hook = IndividualHookConfig(event=event, config=config,
                                    matcher=matcher, source='sessionHook',
                                    hook_id=f'session:{self._counter}')
        self._session_hooks.setdefault(event, []).append(hook)
        return hook.hook_id

    def on(self, event: str, matcher: str = '*', fn=None):
        if fn is not None:
            return self.register(event, matcher=matcher, fn=fn)

        def decorator(f):
            self.register(event, matcher=matcher, fn=f)
            return f

        return decorator

    def configured(self) -> list:
        """Every hook that could run, with where it came from."""
        if self._settings_hooks is None:
            self._settings_hooks = (dedupe_hooks(get_all_hooks(self._cwd))
                                    if self.enabled else [])
        hooks = list(self._settings_hooks) + list(get_builtin_hooks())
        for event in sorted(self._session_hooks):
            hooks.extend(self._session_hooks[event])
        return [{'event': hook.event, 'matcher': hook.matcher,
                 'type': hook.config.type,
                 'source': hook.source or 'settings',
                 'detail': _hook_detail(hook.config)} for hook in hooks]

    def remove_hook(self, hook_id: str):
        for event, hooks in self._session_hooks.items():
            self._session_hooks[event] = [h for h in hooks
                                          if h.hook_id != hook_id]

    def clear(self):
        self._session_hooks.clear()
        self._consumed_once.clear()
        self._background_tasks.clear()

    def get_matching_hooks(self, event: str, query: str,
                           hook_input: dict) -> list:
        if self._settings_hooks is None:
            self._settings_hooks = (dedupe_hooks(get_all_hooks(self._cwd))
                                    if self.enabled else [])
        all_hooks = ([h for h in self._settings_hooks + get_builtin_hooks()
                      if h.event == event]
                     + self._session_hooks.get(event, []))
        if event in ('SessionStart', 'Setup'):
            all_hooks = [h for h in all_hooks if h.config.type != 'http']
        matched = []
        for h in all_hooks:
            if h.hook_id in self._consumed_once:
                continue
            if query and not matches_pattern(query, h.matcher):
                continue
            if h.config.if_:
                if not if_condition_applies(event):
                    continue
                if not if_matches(h.config.if_,
                                  hook_input.get('tool_name') or '',
                                  hook_input.get('tool_input') or {}):
                    continue
            matched.append(h)
        return matched

    async def run(self, event: str, *, query: str = None, input: dict = None,
                  agent=None, tool_use_id: str = '') -> AggregatedHookResult:
        if not self.enabled:
            return AggregatedHookResult()
        hook_input = build_hook_input(
            event, session_id=self._session_id, agent=agent,
            cwd=self._cwd, permission_mode=self.permission_mode,
            tool_use_id=tool_use_id)
        hook_input.update(input or {})
        matched = self.get_matching_hooks(event, query, hook_input)
        if not matched:
            return AggregatedHookResult()
        if agent is not None and any(
                h.config.type in ('function', 'prompt', 'agent')
                for h in matched):
            hook_input['messages'] = agent.messages
        start = time.monotonic()
        tasks = []
        for hook in matched:
            if hook.config.type == 'command' and hook.config.async_:
                tasks.append(self._spawn_background(hook, hook_input))
            else:
                tasks.append(self._run_one(hook, hook_input))
        results = list(await asyncio.gather(*tasks))
        for hook in matched:
            if hook.config.once:
                self._consumed_once.add(hook.hook_id)
        agg = aggregate_results(results,
                                int((time.monotonic() - start) * 1000))
        if agg.system_message:
            emit(AGENT_WARN,
                 agent=getattr(agent, 'name', '') or DEFAULT_PARENT,
                 text=agg.system_message)
        return agg

    async def _run_one(self, hook, hook_input) -> HookResult:
        hook_id = hook.hook_id
        hook_name = get_hook_display_text(hook.config)
        emit_started(hook_id, hook_name, hook.event)
        timeout = hook.config.timeout or DEFAULT_TIMEOUTS[hook.config.type]
        try:
            result = await asyncio.wait_for(self._dispatch(hook, hook_input),
                                            timeout=timeout)
        except asyncio.TimeoutError:
            result = HookResult(hook=hook, outcome='non_blocking_error',
                                message=f'Hook timed out after {timeout}s')
        except Exception as e:
            result = HookResult(hook=hook, outcome='non_blocking_error',
                                message=f'{type(e).__name__}: {e}')
        emit_response(hook_id, hook_name, hook.event, output=result.message,
                      stdout=result.stdout, stderr=result.stderr,
                      exit_code=result.exit_code, outcome=result.outcome)
        return result

    def _spawn_background(self, hook, hook_input) -> HookResult:
        hook_id = hook.hook_id
        hook_name = get_hook_display_text(hook.config)
        emit_started(hook_id, hook_name, hook.event)

        async def run_bg():
            try:
                result = await self._dispatch(hook, hook_input)
            except Exception as e:
                result = HookResult(hook=hook, outcome='non_blocking_error',
                                    message=f'{type(e).__name__}: {e}')
            emit_response(hook_id, hook_name, hook.event,
                          stdout=result.stdout, stderr=result.stderr,
                          exit_code=result.exit_code, outcome=result.outcome)

        task = asyncio.get_running_loop().create_task(run_bg())
        self._background_tasks[hook_id] = task
        task.add_done_callback(lambda t: self._background_tasks.pop(hook_id, None))
        return HookResult(hook=hook, outcome='success', message='backgrounded')

    async def _dispatch(self, hook, hook_input) -> HookResult:
        config = hook.config
        if config.type == 'command':
            return await exec_command_hook(hook, hook_input, self._cwd)
        if config.type == 'http':
            return await exec_http_hook(hook, hook_input)
        if config.type == 'prompt':
            return await exec_prompt_hook(
                self._team._client_for(EVALUATOR_INSTRUCTION,
                thinking=Thinking('off'),
                                       model=config.model or None),
                hook, hook_input)
        if config.type == 'agent':
            parent = hook_input.get('agent_id') or DEFAULT_PARENT
            return await exec_agent_hook(self._team, parent, hook, hook_input)
        if config.type == 'function':
            return await exec_function_hook(hook, hook_input)
        if config.type == 'callback':
            return await exec_callback_hook(
                hook, hook_input.get('hook_event_name') or '', hook_input)
        return HookResult(hook=hook, outcome='non_blocking_error',
                          message=f'unknown hook type {config.type}')

    async def execute_pre_tool_hooks(self, agent, tool_use_id: str,
                                     tool_name: str, tool_input: dict):
        return await self.run(
            'PreToolUse', query=tool_name,
            input={'tool_name': tool_name, 'tool_input': tool_input},
            agent=agent, tool_use_id=tool_use_id)

    async def execute_post_tool_hooks(self, agent, tool_use_id: str,
                                      tool_name: str, tool_input: dict,
                                      tool_response):
        return await self.run(
            'PostToolUse', query=tool_name,
            input={'tool_name': tool_name, 'tool_input': tool_input,
                   'tool_response': tool_response},
            agent=agent, tool_use_id=tool_use_id)

    async def execute_post_tool_failure_hooks(self, agent, tool_use_id: str,
                                              tool_name: str, tool_input: dict,
                                              error):
        return await self.run(
            'PostToolUseFailure', query=tool_name,
            input={'tool_name': tool_name, 'tool_input': tool_input,
                   'error': str(error)},
            agent=agent, tool_use_id=tool_use_id)

    async def execute_user_prompt_submit_hooks(self, agent, prompt: str):
        return await self.run('UserPromptSubmit',
                              input={'prompt': prompt}, agent=agent)

    async def execute_stop_hooks(self, agent, stop_hook_active: bool = False):
        return await self.run('Stop',
                              input={'stop_hook_active': stop_hook_active,
                                     'last_assistant_message':
                                         _last_assistant_text(agent.messages)},
                              agent=agent)

    async def execute_stop_failure_hooks(self, agent, error):
        return await self.run('StopFailure', input={'error': str(error)},
                              agent=agent)

    async def execute_notification_hooks(self, agent, notification_type: str,
                                         message: str, title: str = ''):
        return await self.run(
            'Notification', query=notification_type,
            input={'notification_type': notification_type,
                   'message': message, 'title': title},
            agent=agent)

    async def execute_session_start_hooks(self, source: str = 'startup'):
        return await self.run('SessionStart', query=source,
                              input={'source': source})

    async def execute_session_end_hooks(self, reason: str = 'logout'):
        return await self.run('SessionEnd', query=reason,
                              input={'reason': reason})

    async def execute_setup_hooks(self, trigger: str = 'init'):
        return await self.run('Setup', query=trigger,
                              input={'trigger': trigger})

    async def execute_subagent_start_hooks(self, agent, agent_type: str):
        return await self.run(
            'SubagentStart', query=agent_type,
            input={'agent_id': agent.name, 'agent_type': agent_type},
            agent=agent)

    async def execute_subagent_stop_hooks(self, agent, agent_type: str):
        return await self.run(
            'SubagentStop', query=agent_type,
            input={'agent_id': agent.name, 'agent_type': agent_type,
                   'stop_hook_active': agent._stop_hook_active,
                   'last_assistant_message':
                       _last_assistant_text(agent.messages)},
            agent=agent)

    async def execute_task_created_hooks(self, agent, task_id: str,
                                         task_subject: str,
                                         task_description: str = ''):
        return await self.run(
            'TaskCreated',
            input={'task_id': task_id, 'task_subject': task_subject,
                   'task_description': task_description,
                   'teammate_name': agent.name, 'team_name': self._team.name},
            agent=agent)

    async def execute_task_completed_hooks(self, agent, task_id: str,
                                           task_subject: str,
                                           task_description: str = ''):
        return await self.run(
            'TaskCompleted',
            input={'task_id': task_id, 'task_subject': task_subject,
                   'task_description': task_description,
                   'teammate_name': agent.name, 'team_name': self._team.name},
            agent=agent)

    async def execute_teammate_idle_hooks(self, agent):
        return await self.run(
            'TeammateIdle',
            input={'teammate_name': agent.name, 'team_name': self._team.name},
            agent=agent)

    async def execute_instructions_loaded_hooks(self, agent, file_path: str,
                                                memory_type: str, *,
                                                load_reason: str =
                                                'session_start'):
        return await self.run(
            'InstructionsLoaded', query=load_reason,
            input={'file_path': file_path, 'memory_type': memory_type,
                   'load_reason': load_reason},
            agent=agent)

    async def execute_pre_compact_hooks(self, agent=None, trigger: str = 'manual'):
        return await self.run('PreCompact', query=trigger,
                              input={'trigger': trigger}, agent=agent)

    async def execute_post_compact_hooks(self, agent=None, trigger: str = 'manual'):
        return await self.run('PostCompact', query=trigger,
                              input={'trigger': trigger}, agent=agent)

    async def execute_permission_request_hooks(self, agent, tool_name: str,
                                               tool_input: dict,
                                               tool_use_id: str = '',
                                               permission_suggestions=None):
        input = {'tool_name': tool_name, 'tool_input': tool_input}
        if permission_suggestions:
            input['permission_suggestions'] = list(permission_suggestions)
        return await self.run('PermissionRequest', query=tool_name,
                              input=input, agent=agent,
                              tool_use_id=tool_use_id)

    async def execute_permission_denied_hooks(self, agent, tool_name: str,
                                              tool_input: dict):
        return await self.run('PermissionDenied', query=tool_name,
                              input={'tool_name': tool_name,
                                     'tool_input': tool_input},
                              agent=agent)

    async def execute_elicitation_hooks(self, agent=None, message: str = ''):
        return await self.run('Elicitation', input={'message': message},
                              agent=agent)

    async def execute_elicitation_result_hooks(self, agent=None,
                                               response: str = ''):
        return await self.run('ElicitationResult',
                              input={'response': response}, agent=agent)

    async def execute_config_change_hooks(self, agent=None, source: str = ''):
        return await self.run('ConfigChange', query=source,
                              input={'source': source}, agent=agent)

    async def execute_worktree_create_hooks(self, agent=None,
                                            worktree_name: str = ''):
        return await self.run('WorktreeCreate',
                              input={'worktree_name': worktree_name},
                              agent=agent)

    async def execute_worktree_remove_hooks(self, agent=None,
                                            worktree_name: str = ''):
        return await self.run('WorktreeRemove',
                              input={'worktree_name': worktree_name},
                              agent=agent)

    async def execute_file_changed_hooks(self, agent=None, file_path: str = ''):
        return await self.run('FileChanged', query=file_path.split('/')[-1],
                              input={'file_path': file_path}, agent=agent)

    async def execute_cwd_changed_hooks(self, agent=None, cwd: str = ''):
        return await self.run('CwdChanged', input={'cwd': cwd}, agent=agent)
