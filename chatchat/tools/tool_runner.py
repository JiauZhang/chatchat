import time
from pathlib import Path

from chatchat.runtime.agent import Agent
from chatchat.team.rules import note as _rule_note
from chatchat.hooks.events import AGENT_TOOL_RESULT, emit
from chatchat.tool import ToolOutcome, ToolResult


def _joined(*parts: str) -> str:
    return "\n".join(p for p in parts if p)


class ToolRunnerMixin:
    async def _post_tool_context(self, agent, tool_use_id: str, name: str, input: dict, value, failed: bool = False) -> str:
        if agent is None or agent.hookless:
            return ""
        if failed:
            agg = await self.hooks.execute_post_tool_failure_hooks(agent, tool_use_id, name, input, value)
        else:
            agg = await self.hooks.execute_post_tool_hooks(agent, tool_use_id, name, input, value)
        return agg.additional_context

    def _changed_file(self, tool, input: dict) -> str:
        if tool is None or tool.read_only or tool.get_path is None:
            return ""
        raw = tool.get_path(input)
        if not raw:
            return ""
        cwd = Path(self.tool_context.cwd).resolve()
        path = Path(str(raw)).expanduser()
        path = path if path.is_absolute() else cwd / path
        path = path.resolve()
        return str(path) if path.is_relative_to(cwd) else ""

    async def _note_file_changed(self, agent, tool, input: dict) -> str:
        path = self._changed_file(tool, input)
        if not path or agent is None or agent.hookless:
            return ""
        agg = await self.hooks.execute_file_changed_hooks(agent, path)
        return agg.additional_context

    def _matched_rules(self, tool, input: dict, result) -> str:
        if self.rules is None or tool is None or not tool.read_only:
            return ""
        if tool.get_path is None:
            return ""
        if str(result).startswith("Error"):
            return ""
        raw = tool.get_path(input)
        if not raw:
            return ""
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path(self.tool_context.cwd) / path
        return _rule_note(self.rules.relevant(str(path)), str(raw))

    def _tool_paths(self, tool, input: dict) -> list[str]:
        if tool is None or tool.get_path is None:
            return []
        raw = tool.get_path(input)
        if not raw:
            return []
        path = Path(str(raw)).expanduser()
        path = path if path.is_absolute() else Path(self.tool_context.cwd) / path
        return [str(path)]

    def _activate_conditional_skills(self, tool, input: dict) -> None:
        skills = getattr(self, "skills", None)
        if skills is None:
            return
        skills.activate_for_paths(self._tool_paths(tool, input))

    def reset_rules(self) -> None:
        if self.rules is not None:
            self.rules.reset()

    async def execute_tool(self, name: str, input: dict, agent: Agent, tool_use_id: str = "") -> ToolOutcome:
        started = time.monotonic()

        def noted(meta: dict | None = None) -> None:
            if agent is None:
                return
            meta = meta or {}
            agent.metrics.tool_ran(
                int((time.monotonic() - started) * 1000),
                added=int(meta.get("num_added") or 0),
                removed=int(meta.get("num_removed") or 0),
            )

        outcome = await self._run_tool(name, input, agent, tool_use_id, noted)
        if outcome.denied and agent is not None:
            agent.metrics.denials += 1
        return outcome

    async def _run_tool(self, name: str, input: dict, agent: Agent, tool_use_id: str, noted) -> ToolOutcome:
        pool = self.tools.injected if (agent is None or agent.tools is None) else agent.tools
        team_tool = self.tools.find_own(name)
        extra = ""
        permission = ""
        reason = ""
        if agent is not None and not agent.hookless:
            pre = await self.hooks.execute_pre_tool_hooks(agent, tool_use_id, name, input)
            if pre.blocking_error is not None:
                return ToolOutcome(f'Error: hook blocked tool "{name}": {pre.blocking_error.blocking_error}', denied=True)
            if pre.updated_input is not None:
                input = {**input, **pre.updated_input}
            extra = pre.additional_context
            permission = pre.decision
            reason = pre.reason
        # The permission gate runs after the hooks, on the input the hooks left
        # behind, and a hook's allow decision satisfies its ask - claude-code's
        # ordering (hook results converge, then the permission flow).
        gate_fn = getattr(self, "permission_gate", None)
        if gate_fn is not None and agent is not None and not agent.hookless:
            outcome = await gate_fn(
                {
                    "tool_name": name,
                    "tool_input": input,
                    "agent_id": agent.name,
                    "agent_type": getattr(agent, "agent_type", "") or ("subagent" if agent._internal else None),
                    "tool_use_id": tool_use_id,
                    "hook_allowed": permission == "allow",
                    "hook_ask": permission == "ask",
                    "hook_reason": reason,
                }
            )
            specific = outcome.get("hookSpecificOutput") or {} if isinstance(outcome, dict) else {}
            if specific.get("permissionDecision") == "deny":
                reason = specific.get("permissionDecisionReason") or f"{name} was denied"
                return ToolOutcome(f"Error: {reason}", extra, denied=True)
            if specific.get("updatedInput"):
                input = {**input, **specific["updatedInput"]}
            feedback = specific.get("additionalContext") or ""
            if feedback:
                extra = f"{extra}\n{feedback}" if extra else feedback
        if team_tool is not None:
            try:
                context = agent.tool_context if agent is not None else self.tool_context
                out = await team_tool(context, team=self, agent=agent, input=input, tool_use_id=tool_use_id)
            except Exception as e:
                noted()
                return ToolOutcome(
                    f'Error calling tool "{name}": {type(e).__name__}: {e}',
                    _joined(extra, await self._post_tool_context(agent, tool_use_id, name, input, e, True)),
                )
            if out is not None:
                noted()
                return ToolOutcome(out, _joined(extra, await self._post_tool_context(agent, tool_use_id, name, input, out)))
        tool = next((t for t in pool if t.name == name), None)
        if tool is None:
            return ToolOutcome(f'Error: tool "{name}" is not available to this agent', extra)
        self._activate_conditional_skills(tool, input)
        try:
            out = await tool(agent.tool_context, **input)
        except Exception as e:
            noted()
            return ToolOutcome(
                f'Error calling tool "{name}": {type(e).__name__}: {e}',
                _joined(extra, await self._post_tool_context(agent, tool_use_id, name, input, e, True)),
            )
        if isinstance(out, ToolResult):
            noted(out.meta)
            emit(AGENT_TOOL_RESULT, agent=getattr(agent, "name", ""), tool=name, tool_use_id=tool_use_id, **(out.meta or {}))
            blocks = list(out.blocks)
            out = out.text
        else:
            noted()
            blocks = []
            if not isinstance(out, str):
                out = str(out)
        return ToolOutcome(
            out,
            _joined(
                extra,
                await self._post_tool_context(agent, tool_use_id, name, input, out),
                self._matched_rules(tool, input, out),
                await self._note_file_changed(agent, tool, input),
            ),
            blocks=blocks,
        )
