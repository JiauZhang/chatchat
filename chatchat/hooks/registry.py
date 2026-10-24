"""The hooks a session has, and which of them apply to an event.

A hook is registered against an event and a matcher. Which hooks run for a
given event is a question about the hooks, not about the session, so it is
answered here: the registry knows what is registered, the settings know what
the project configured, and the built-ins are always available.
"""

from chatchat.hooks.catalog import EVENTS_BY_NAME
from chatchat.hooks.matchers import if_condition_applies, if_matches, matches_pattern
from chatchat.hooks.schemas import HookCommand, IndividualHookConfig
from chatchat.hooks.settings import dedupe_hooks, get_all_hooks, get_builtin_hooks

_ALLOWED_FIELDS = {
    "command",
    "prompt",
    "url",
    "if_",
    "shell",
    "timeout",
    "status_message",
    "once",
    "async_",
    "async_rewake",
    "model",
    "headers",
    "allowed_env_vars",
    "fn",
    "error_message",
    "internal",
}


def _hook_detail(config: HookCommand) -> str:
    if config.type == "command":
        return config.command or ""
    if config.type == "http":
        return config.url or ""
    if config.type in ("prompt", "agent"):
        return (config.prompt or "")[:80]
    return ""


class HookRegistry:
    """What hooks exist, and which of them an event would run.

    Session hooks are the ones the running code registered; settings hooks
    are what the project's settings.json configured; built-in hooks are
    always there. A hook that has already run once is remembered and does not
    run again.
    """

    def __init__(self, cwd: str = ""):
        self._cwd = cwd
        self._session_hooks: dict[str, list[IndividualHookConfig]] = {}
        self._settings_hooks: list[IndividualHookConfig] | None = None
        self._consumed_once: set[str] = set()
        self._counter = 0

    def set_cwd(self, path) -> None:
        self._cwd = str(path)
        self._settings_hooks = None

    def register(self, event: str, matcher: str = "*", **kw) -> str:
        htype = kw.pop("type", None)
        fn = kw.get("fn")
        if htype is None:
            if fn is not None:
                htype = "function"
            elif kw.get("command"):
                htype = "command"
            elif kw.get("url"):
                htype = "http"
            elif kw.get("prompt"):
                htype = "prompt"
            else:
                raise ValueError("hook needs fn/command/prompt/url")
        config = HookCommand(type=htype, **{k: v for k, v in kw.items() if k in _ALLOWED_FIELDS})
        self._counter += 1
        hook = IndividualHookConfig(
            event=event, config=config, matcher=matcher, source="sessionHook", hook_id=f"session:{self._counter}"
        )
        self._session_hooks.setdefault(event, []).append(hook)
        return hook.hook_id

    def on(self, event: str, matcher: str = "*", fn=None):
        if fn is not None:
            return self.register(event, matcher=matcher, fn=fn)

        def decorator(f):
            self.register(event, matcher=matcher, fn=f)
            return f

        return decorator

    def remove_hook(self, hook_id: str):
        for event, hooks in self._session_hooks.items():
            self._session_hooks[event] = [h for h in hooks if h.hook_id != hook_id]

    def clear(self):
        self._session_hooks.clear()
        self._consumed_once.clear()

    def has(self, event: str) -> bool:
        if any(hook.event == event for hook in self._settings() + get_builtin_hooks()):
            return True
        return bool(self._session_hooks.get(event))

    def configured(self) -> list:
        """Every hook that could run, with where it came from."""
        hooks = list(self._settings()) + list(get_builtin_hooks())
        for event in sorted(self._session_hooks):
            hooks.extend(self._session_hooks[event])
        return [
            {
                "event": hook.event,
                "matcher": hook.matcher,
                "type": hook.config.type,
                "source": hook.source or "settings",
                "detail": _hook_detail(hook.config),
            }
            for hook in hooks
        ]

    def matching(self, event: str, query: str, hook_input: dict) -> list:
        """The hooks this event would run, in the order they would run in."""
        all_hooks = [h for h in self._settings() + get_builtin_hooks() if h.event == event]
        all_hooks += self._session_hooks.get(event, [])
        if event in ("SessionStart", "Setup"):
            all_hooks = [h for h in all_hooks if h.config.type != "http"]
        matched = []
        for hook in all_hooks:
            if hook.hook_id in self._consumed_once:
                continue
            if query and not matches_pattern(query, hook.matcher):
                continue
            if hook.config.if_:
                if not if_condition_applies(event):
                    continue
                if not if_matches(hook.config.if_, hook_input.get("tool_name") or "", hook_input.get("tool_input") or {}):
                    continue
            matched.append(hook)
        return matched

    def consumed(self, hook_ids):
        """Remember that these hooks have run, so a once hook does not run again."""
        for hook_id in hook_ids:
            self._consumed_once.add(hook_id)

    def known(self, event: str) -> bool:
        return event in EVENTS_BY_NAME

    def _settings(self) -> list:
        if self._settings_hooks is None:
            self._settings_hooks = dedupe_hooks(get_all_hooks(self._cwd))
        return self._settings_hooks
