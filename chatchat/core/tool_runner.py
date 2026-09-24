import time
from pathlib import Path

import chatchat.core.tools as _tools
from chatchat.core.agent import Agent
from chatchat.core.rules import note as _rule_note
from chatchat.core.structured import STRUCTURED_OUTPUT_TOOL
from chatchat.hooks.events import AGENT_TOOL_RESULT, emit
from chatchat.tool import ToolOutcome, ToolResult


def _joined(*parts: str) -> str:
    return '\n'.join(p for p in parts if p)



class ToolRunnerMixin:
    async def _post_tool_context(self, agent, tool_use_id: str, name: str,
                                 input: dict, value,
                                 failed: bool = False) -> str:
        if agent is None or agent.hookless:
            return ''
        if failed:
            agg = await self.hooks.execute_post_tool_failure_hooks(
                agent, tool_use_id, name, input, value)
        else:
            agg = await self.hooks.execute_post_tool_hooks(
                agent, tool_use_id, name, input, value)
        return agg.additional_context

    def _changed_file(self, tool, input: dict) -> str:
        if tool is None or tool.read_only or tool.get_path is None:
            return ''
        raw = tool.get_path(input)
        if not raw:
            return ''
        cwd = Path(self.tool_context.cwd).resolve()
        path = Path(str(raw)).expanduser()
        path = path if path.is_absolute() else cwd / path
        path = path.resolve()
        return str(path) if path.is_relative_to(cwd) else ''

    async def _note_file_changed(self, agent, tool, input: dict) -> str:
        path = self._changed_file(tool, input)
        if not path or agent is None or agent.hookless:
            return ''
        agg = await self.hooks.execute_file_changed_hooks(agent, path)
        return agg.additional_context

    def _matched_rules(self, tool, input: dict, result) -> str:
        if self.rules is None or tool is None or not tool.read_only:
            return ''
        if tool.get_path is None:
            return ''
        if str(result).startswith('Error'):
            return ''
        raw = tool.get_path(input)
        if not raw:
            return ''
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path(self.tool_context.cwd) / path
        return _rule_note(self.rules.relevant(str(path)), str(raw))

    def reset_rules(self) -> None:
        if self.rules is not None:
            self.rules.reset()

    async def execute_tool(self, name: str, input: dict, agent: Agent,
                           tool_use_id: str = '') -> ToolOutcome:
        started = time.monotonic()

        def noted(meta: dict | None = None) -> None:
            if agent is None:
                return
            meta = meta or {}
            agent.metrics.tool_ran(
                int((time.monotonic() - started) * 1000),
                added=int(meta.get('num_added') or 0),
                removed=int(meta.get('num_removed') or 0))

        outcome = await self._run_tool(name, input, agent, tool_use_id, noted)
        if outcome.denied and agent is not None:
            agent.metrics.denials += 1
        return outcome

    async def _run_tool(self, name: str, input: dict, agent: Agent,
                        tool_use_id: str, noted) -> ToolOutcome:
        pool = self._injected_tools if (agent is None
                                        or agent.tools is None) else agent.tools
        team_fns = ({} if agent is not None and agent.tools is not None
                    else {'send_message': _tools.send_message,
                          'create_agent': _tools.create_agent,
                          'task_stop': _tools.task_stop})
        if self.tasks is not None:
            team_fns |= {'task_create': _tools.task_create,
                         'task_list': _tools.task_list,
                         'task_get': _tools.task_get,
                         'task_update': _tools.task_update}
        if self.multi_agent:
            team_fns |= {'team_create': _tools.team_create,
                         'team_delete': _tools.team_delete}
        if self.skills.all():
            team_fns['use_skill'] = _tools.use_skill
        if self._worktrees:
            team_fns |= {'enter_worktree': _tools.enter_worktree,
                         'exit_worktree': _tools.exit_worktree}
        if self.ask_user is not None:
            team_fns['ask_user'] = _tools.ask_user
        if self.cron is not None:
            team_fns |= {'cron_create': _tools.cron_create,
                         'cron_list': _tools.cron_list,
                         'cron_delete': _tools.cron_delete}
        if self.output_schema is not None:
            team_fns[STRUCTURED_OUTPUT_TOOL] = _tools.structured_output
        extra = ''
        if agent is not None and not agent.hookless:
            pre = await self.hooks.execute_pre_tool_hooks(
                agent, tool_use_id, name, input)
            if pre.blocking_error is not None:
                return ToolOutcome(
                    f'Error: hook blocked tool "{name}": '
                    f'{pre.blocking_error.blocking_error}', denied=True)
            if pre.updated_input is not None:
                input = {**input, **pre.updated_input}
            extra = pre.additional_context
        fn = team_fns.get(name)
        if fn is None:
            tool = next((t for t in pool if t.name == name), None)
            if tool is None:
                return ToolOutcome(
                    f'Error: tool "{name}" is not available to this agent',
                    extra)
            try:
                out = await tool(agent.tool_context, **input)
            except Exception as e:
                noted()
                return ToolOutcome(
                    f'Error calling tool "{name}": {type(e).__name__}: {e}',
                    _joined(extra, await self._post_tool_context(
                        agent, tool_use_id, name, input, e, True)))
            if isinstance(out, ToolResult):
                noted(out.meta)
                emit(AGENT_TOOL_RESULT,
                     agent=getattr(agent, 'name', ''),
                     tool=name, tool_use_id=tool_use_id,
                     **(out.meta or {}))
                out = out.text
            else:
                noted()
                if not isinstance(out, str):
                    out = str(out)
            return ToolOutcome(out, _joined(extra, await self._post_tool_context(
                agent, tool_use_id, name, input, out),
                self._matched_rules(tool, input, out),
                await self._note_file_changed(agent, tool, input)))
        try:
            out = await fn(self, agent, input, tool_use_id)
        except Exception as e:
            noted()
            return ToolOutcome(
                f'Error calling tool "{name}": {type(e).__name__}: {e}',
                _joined(extra, await self._post_tool_context(
                    agent, tool_use_id, name, input, e, True)))
        noted()
        return ToolOutcome(out, _joined(extra, await self._post_tool_context(
            agent, tool_use_id, name, input, out)))
