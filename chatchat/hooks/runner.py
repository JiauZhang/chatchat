"""Running the hooks an event matched.

The runner knows how to run a hook of each kind and how to gather what they
said. It does not know which hooks exist - the registry knows that - and it
does not know what a session is: what it needs from one, it is handed.
"""

import asyncio

from chatchat.hooks.events import AGENT_WARN, emit, emit_response, emit_started
from chatchat.hooks.executors import (
    EVALUATOR_INSTRUCTION,
    exec_agent_hook,
    exec_callback_hook,
    exec_command_hook,
    exec_function_hook,
    exec_http_hook,
    exec_prompt_hook,
)
from chatchat.hooks.output import aggregate_results
from chatchat.hooks.schemas import DEFAULT_TIMEOUTS, HookResult, get_hook_display_text

DEFAULT_PARENT = "team-lead"


def build_hook_input(
    event: str,
    *,
    session_id: str,
    agent=None,
    cwd: str = "",
    permission_mode: str = "",
    transcript_path: str = "",
    **fields,
) -> dict:
    hook_input = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "agent_id": agent.name if agent else None,
        "agent_type": (
            getattr(agent, "agent_type", "") or ("subagent" if getattr(agent, "_internal", False) else None) if agent else None
        ),
        "hook_event_name": event,
    }
    if permission_mode:
        hook_input["permission_mode"] = permission_mode
    hook_input.update(fields)
    return hook_input


def last_assistant_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


class HookRunner:
    """Runs the hooks that matched, and says what they answered.

    A prompt hook needs a client to ask, and an agent hook needs somewhere to
    run; both are handed in, so the runner never has to reach into a session
    for them.
    """

    def __init__(self, *, make_client=None, spawn_agent=None):
        self._make_client = make_client
        self._spawn_agent = spawn_agent
        self._background_tasks: dict[str, asyncio.Task] = {}

    def clear(self):
        self._background_tasks.clear()

    async def close(self):
        """Stop the hooks that are still running in the background.

        A background hook is a command of its own; leaving it running when
        the session ends would leave it running after nobody is listening.
        """
        tasks = list(self._background_tasks.values())
        self._background_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def run_one(self, hook, hook_input, cwd: str) -> HookResult:
        hook_id = hook.hook_id
        hook_name = get_hook_display_text(hook.config)
        emit_started(hook_id, hook_name, hook.event)
        timeout = hook.config.timeout or DEFAULT_TIMEOUTS[hook.config.type]
        try:
            result = await asyncio.wait_for(self._dispatch(hook, hook_input, cwd), timeout=timeout)
        except asyncio.TimeoutError:
            result = HookResult(hook=hook, outcome="non_blocking_error", message=f"Hook timed out after {timeout}s")
        except Exception as e:
            result = HookResult(hook=hook, outcome="non_blocking_error", message=f"{type(e).__name__}: {e}")
        emit_response(
            hook_id,
            hook_name,
            hook.event,
            output=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            outcome=result.outcome,
        )
        return result

    async def spawn_background(self, hook, hook_input, cwd: str, agent=None) -> HookResult:
        """Run the hook in the background and answer at once.

        The caller is not held up by the hook; it is told the hook was
        backgrounded and carries on. What the hook said later is told to
        whoever is listening.
        """
        hook_id = hook.hook_id
        hook_name = get_hook_display_text(hook.config)
        emit_started(hook_id, hook_name, hook.event)

        async def run_bg():
            try:
                result = await self._dispatch(hook, hook_input, cwd)
            except Exception as e:
                result = HookResult(hook=hook, outcome="non_blocking_error", message=f"{type(e).__name__}: {e}")
            emit_response(
                hook_id,
                hook_name,
                hook.event,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                outcome=result.outcome,
            )
            if hook.config.async_rewake:
                self._rewake(hook, result, agent)

        task = asyncio.get_running_loop().create_task(run_bg())
        self._background_tasks[hook_id] = task
        task.add_done_callback(lambda t: self._background_tasks.pop(hook_id, None))
        return HookResult(hook=hook, outcome="success", message="backgrounded")

    @staticmethod
    def _rewake(hook, result, agent):
        """A background hook that blocked tells the model, and wakes it up.

        The hook ran on its own and said something the model needs to hear:
        exit code two is a blocking error, and the model is the one that has
        to answer it. The message rides in as a system reminder, so it is
        part of the conversation rather than something said in passing.
        """
        if agent is None or result.exit_code != 2:
            return
        text = result.stderr or result.stdout
        if not text.strip():
            return
        name = get_hook_display_text(hook.config)
        agent.wake_from_hook(f'<system-reminder>\nStop hook blocking error from command "{name}": {text}\n</system-reminder>')

    async def _dispatch(self, hook, hook_input, cwd: str) -> HookResult:
        config = hook.config
        if config.type == "command":
            return await exec_command_hook(hook, hook_input, cwd)
        if config.type == "http":
            return await exec_http_hook(hook, hook_input)
        if config.type == "prompt":
            if self._make_client is None:
                return HookResult(hook=hook, outcome="non_blocking_error", message="no client for a prompt hook")
            return await exec_prompt_hook(self._make_client(config.model or None), hook, hook_input)
        if config.type == "agent":
            if self._spawn_agent is None:
                return HookResult(hook=hook, outcome="non_blocking_error", message="no agent for an agent hook")
            parent = hook_input.get("agent_id") or DEFAULT_PARENT
            return await exec_agent_hook(self._spawn_agent, parent, hook, hook_input)
        if config.type == "function":
            return await exec_function_hook(hook, hook_input)
        if config.type == "callback":
            return await exec_callback_hook(hook, hook_input.get("hook_event_name") or "", hook_input)
        return HookResult(hook=hook, outcome="non_blocking_error", message=f"unknown hook type {config.type}")

    @staticmethod
    def warn(agent, system_message: str):
        emit(AGENT_WARN, agent=getattr(agent, "name", "") or DEFAULT_PARENT, text=system_message)


__all__ = ["EVALUATOR_INSTRUCTION", "HookRunner", "aggregate_results", "build_hook_input", "last_assistant_text"]
