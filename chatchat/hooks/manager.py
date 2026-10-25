"""The hook events a session fires, and where they go.

The manager is the seam between the runtime and the hooks: the runtime says
what happened, the manager finds the hooks that apply, runs them and reports
what they said.

Each event has one method, because each event carries its own facts. What
they do not carry is the matcher: a matcher is compared against the field
the event matches on, and that field is the same for every hook of that
event, so it is decided once in the catalog rather than written out again at
every call site.
"""

import asyncio
import os
import time
import uuid

from chatchat.hooks.catalog import match_query
from chatchat.hooks.output import aggregate_results
from chatchat.hooks.registry import HookRegistry
from chatchat.hooks.runner import HookRunner, build_hook_input, last_assistant_text
from chatchat.hooks.schemas import AggregatedHookResult


class HookManager:
    def __init__(self, team=None, enabled: bool = True, *, make_client=None, spawn_agent=None):
        self.enabled = enabled
        self._team = team
        self._cwd = os.getcwd()
        self._session_id = uuid.uuid4().hex
        self.permission_mode = ""
        self.registry = HookRegistry(self._cwd)
        self.runner = HookRunner(make_client=make_client, spawn_agent=spawn_agent)

    def register(self, event: str, matcher: str = "*", **kw) -> str:
        return self.registry.register(event, matcher, **kw)

    def on(self, event: str, matcher: str = "*", fn=None):
        return self.registry.on(event, matcher, fn)

    def has(self, event: str) -> bool:
        if not self.enabled:
            return False
        return self.registry.has(event)

    def configured(self) -> list:
        """Every hook that could run, with where it came from."""
        if not self.enabled:
            return []
        return self.registry.configured()

    def remove_hook(self, hook_id: str):
        self.registry.remove_hook(hook_id)

    def clear(self):
        self.registry.clear()
        self.runner.clear()

    async def close(self):
        """Let go of the hooks that are still running."""
        await self.runner.close()

    def get_matching_hooks(self, event: str, query: str, hook_input: dict) -> list:
        return self.registry.matching(event, query, hook_input)

    def set_cwd(self, path) -> None:
        self._cwd = str(path)
        self.registry.set_cwd(path)

    async def run(
        self, event: str, *, query: str = None, input: dict = None, agent=None, tool_use_id: str = ""
    ) -> AggregatedHookResult:
        if not self.enabled:
            return AggregatedHookResult()
        hook_input = build_hook_input(
            event,
            session_id=self._session_id,
            agent=agent,
            cwd=self._cwd,
            permission_mode=self.permission_mode,
            tool_use_id=tool_use_id,
        )
        hook_input.update(input or {})
        if query is None:
            query = match_query(event, hook_input)
        matched = self.registry.matching(event, query, hook_input)
        if not matched:
            return AggregatedHookResult()
        if agent is not None and any(h.config.type in ("function", "prompt", "agent") for h in matched):
            hook_input["messages"] = agent.messages
        start = time.monotonic()
        tasks = []
        for hook in matched:
            if hook.config.type == "command" and (hook.config.async_ or hook.config.async_rewake):
                tasks.append(self.runner.spawn_background(hook, hook_input, self._cwd, agent))
            else:
                tasks.append(self.runner.run_one(hook, hook_input, self._cwd))
        results = list(await asyncio.gather(*tasks))
        self.registry.consumed(h.hook_id for h in matched if h.config.once)
        agg = aggregate_results(results, int((time.monotonic() - start) * 1000))
        if agent is not None and matched:
            agent.metrics.hook_ran(agg.total_duration_ms)
        if agg.system_message:
            self.runner.warn(agent, agg.system_message)
        return agg

    async def execute_pre_tool_hooks(self, agent, tool_use_id: str, tool_name: str, tool_input: dict):
        return await self.run(
            "PreToolUse",
            input={"tool_name": tool_name, "tool_input": tool_input},
            agent=agent,
            tool_use_id=tool_use_id,
        )

    async def execute_post_tool_hooks(self, agent, tool_use_id: str, tool_name: str, tool_input: dict, tool_response):
        return await self.run(
            "PostToolUse",
            input={"tool_name": tool_name, "tool_input": tool_input, "tool_response": tool_response},
            agent=agent,
            tool_use_id=tool_use_id,
        )

    async def execute_post_tool_failure_hooks(self, agent, tool_use_id: str, tool_name: str, tool_input: dict, error):
        return await self.run(
            "PostToolUseFailure",
            input={"tool_name": tool_name, "tool_input": tool_input, "error": str(error)},
            agent=agent,
            tool_use_id=tool_use_id,
        )

    async def execute_user_prompt_submit_hooks(self, agent, prompt: str):
        return await self.run("UserPromptSubmit", input={"prompt": prompt}, agent=agent)

    async def execute_stop_hooks(self, agent, stop_hook_active: bool = False):
        return await self.run(
            "Stop",
            input={"stop_hook_active": stop_hook_active, "last_assistant_message": last_assistant_text(agent.messages)},
            agent=agent,
        )

    async def execute_stop_failure_hooks(self, agent, error):
        return await self.run("StopFailure", input={"error": str(error)}, agent=agent)

    async def execute_notification_hooks(self, agent, notification_type: str, message: str, title: str = ""):
        return await self.run(
            "Notification",
            input={"notification_type": notification_type, "message": message, "title": title},
            agent=agent,
        )

    async def execute_session_start_hooks(self, source: str = "startup"):
        return await self.run("SessionStart", input={"source": source})

    async def execute_session_end_hooks(self, reason: str = "logout"):
        return await self.run("SessionEnd", input={"reason": reason})

    async def execute_setup_hooks(self, trigger: str = "init"):
        return await self.run("Setup", input={"trigger": trigger})

    async def execute_subagent_start_hooks(self, agent, agent_type: str):
        return await self.run("SubagentStart", input={"agent_id": agent.name, "agent_type": agent_type}, agent=agent)

    async def execute_subagent_stop_hooks(self, agent, agent_type: str):
        return await self.run(
            "SubagentStop",
            input={
                "agent_id": agent.name,
                "agent_type": agent_type,
                "stop_hook_active": agent._stop_hook_active,
                "last_assistant_message": last_assistant_text(agent.messages),
            },
            agent=agent,
        )

    async def execute_task_created_hooks(self, agent, task_id: str, task_subject: str, task_description: str = ""):
        return await self.run(
            "TaskCreated",
            input={
                "task_id": task_id,
                "task_subject": task_subject,
                "task_description": task_description,
                "teammate_name": agent.name,
                "team_name": self._team_name(),
            },
            agent=agent,
        )

    async def execute_task_completed_hooks(self, agent, task_id: str, task_subject: str, task_description: str = ""):
        return await self.run(
            "TaskCompleted",
            input={
                "task_id": task_id,
                "task_subject": task_subject,
                "task_description": task_description,
                "teammate_name": agent.name,
                "team_name": self._team_name(),
            },
            agent=agent,
        )

    async def execute_teammate_idle_hooks(self, agent):
        return await self.run("TeammateIdle", input={"teammate_name": agent.name, "team_name": self._team_name()}, agent=agent)

    async def execute_instructions_loaded_hooks(
        self, agent, file_path: str, memory_type: str, *, load_reason: str = "session_start"
    ):
        return await self.run(
            "InstructionsLoaded",
            input={"file_path": file_path, "memory_type": memory_type, "load_reason": load_reason},
            agent=agent,
        )

    async def execute_pre_compact_hooks(self, agent=None, trigger: str = "manual"):
        return await self.run("PreCompact", input={"trigger": trigger}, agent=agent)

    async def execute_post_compact_hooks(self, agent=None, trigger: str = "manual"):
        return await self.run("PostCompact", input={"trigger": trigger}, agent=agent)

    async def execute_permission_request_hooks(
        self, agent, tool_name: str, tool_input: dict, tool_use_id: str = "", permission_suggestions=None
    ):
        input = {"tool_name": tool_name, "tool_input": tool_input}
        if permission_suggestions:
            input["permission_suggestions"] = list(permission_suggestions)
        return await self.run("PermissionRequest", input=input, agent=agent, tool_use_id=tool_use_id)

    async def execute_permission_denied_hooks(self, agent, tool_name: str, tool_input: dict):
        return await self.run("PermissionDenied", input={"tool_name": tool_name, "tool_input": tool_input}, agent=agent)

    async def execute_elicitation_hooks(self, agent=None, message: str = ""):
        return await self.run("Elicitation", input={"message": message}, agent=agent)

    async def execute_elicitation_result_hooks(self, agent=None, response: str = ""):
        return await self.run("ElicitationResult", input={"response": response}, agent=agent)

    async def execute_config_change_hooks(self, agent=None, source: str = ""):
        return await self.run("ConfigChange", input={"source": source}, agent=agent)

    async def execute_worktree_create_hooks(self, agent=None, name: str = ""):
        return await self.run("WorktreeCreate", input={"name": name}, agent=agent)

    async def execute_worktree_remove_hooks(self, agent=None, worktree_path: str = ""):
        return await self.run("WorktreeRemove", input={"worktree_path": worktree_path}, agent=agent)

    async def execute_file_changed_hooks(self, agent=None, file_path: str = ""):
        return await self.run("FileChanged", input={"file_path": file_path}, agent=agent)

    async def execute_cwd_changed_hooks(self, agent=None, cwd: str = ""):
        return await self.run("CwdChanged", input={"cwd": cwd}, agent=agent)

    def _team_name(self) -> str:
        return getattr(self._team, "name", "") or ""
