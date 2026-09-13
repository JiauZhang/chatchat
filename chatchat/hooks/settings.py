import json
from pathlib import Path

from chatchat.hooks.schemas import (DEFAULT_HOOK_SHELL, HOOK_TYPES,
                                    HookCommand, IndividualHookConfig)

_SETTINGS_FIELD_MAP = {
    'if': 'if_',
    'statusMessage': 'status_message',
    'async': 'async_',
    'asyncRewake': 'async_rewake',
    'allowedEnvVars': 'allowed_env_vars',
}

_builtin_hooks: list[IndividualHookConfig] = []


def settings_file_paths(cwd):
    return {
        'userSettings': Path.home() / '.chatchat' / 'settings.json',
        'projectSettings': Path(cwd) / '.chatchat' / 'settings.json',
        'localSettings': Path(cwd) / '.chatchat' / 'settings.local.json',
    }


def hook_from_dict(data: dict) -> HookCommand | None:
    htype = data.get('type')
    if htype not in HOOK_TYPES or htype in ('function', 'callback'):
        return None
    kw = {}
    for key, value in data.items():
        if key == 'type':
            continue
        field_name = _SETTINGS_FIELD_MAP.get(key, key)
        kw[field_name] = value
    return HookCommand(type=htype, **{k: v for k, v in kw.items()
                                      if k in HookCommand.__dataclass_fields__})


def _load_file(path: Path, source: str) -> list[IndividualHookConfig]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (ValueError, TypeError, OSError):
        return []
    hooks = data.get('hooks') if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return []
    out = []
    for event, matcher_entries in hooks.items():
        if not isinstance(matcher_entries, list):
            continue
        for entry in matcher_entries:
            if not isinstance(entry, dict) or 'hooks' not in entry:
                continue
            matcher = entry.get('matcher') or '*'
            for hdict in entry['hooks']:
                if not isinstance(hdict, dict):
                    continue
                config = hook_from_dict(hdict)
                if config is None:
                    continue
                out.append(IndividualHookConfig(
                    event=event, config=config, matcher=matcher,
                    source=source))
    return out


def get_all_hooks(cwd):
    out = []
    seen_files = set()
    for source, path in settings_file_paths(cwd).items():
        resolved = path.resolve()
        if resolved in seen_files:
            continue
        seen_files.add(resolved)
        out.extend(_load_file(resolved, source))
    for i, h in enumerate(out):
        h.hook_id = f'{h.source}:{i}'
    return out


def is_hook_equal(a: HookCommand, b: HookCommand) -> bool:
    if a.type != b.type:
        return False
    same_if = (a.if_ or '') == (b.if_ or '')
    if a.type == 'command':
        return (a.command == b.command
                and (a.shell or DEFAULT_HOOK_SHELL) == (b.shell or DEFAULT_HOOK_SHELL)
                and same_if)
    if a.type in ('prompt', 'agent'):
        return a.prompt == b.prompt and same_if
    if a.type == 'http':
        return a.url == b.url and same_if
    return False


def dedupe_hooks(hooks: list[IndividualHookConfig]) -> list[IndividualHookConfig]:
    out = []
    for h in hooks:
        if any(k.event == h.event and is_hook_equal(k.config, h.config)
               for k in out):
            continue
        out.append(h)
    return out


def register_builtin(event: str, matcher: str, hook: HookCommand):
    _builtin_hooks.append(IndividualHookConfig(
        event=event, config=hook, matcher=matcher, source='builtinHook',
        hook_id=f'builtin:{len(_builtin_hooks)}'))


def get_builtin_hooks() -> list[IndividualHookConfig]:
    return list(_builtin_hooks)
