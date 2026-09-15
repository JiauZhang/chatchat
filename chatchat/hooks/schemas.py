from dataclasses import dataclass, field

DEFAULT_HOOK_SHELL = 'bash'

HOOK_TYPES = ('command', 'prompt', 'http', 'agent', 'function', 'callback')

DEFAULT_TIMEOUTS = {
    'command': 60.0,
    'prompt': 60.0,
    'agent': 60.0,
    'http': 600.0,
    'function': 5.0,
    'callback': 5.0,
}


@dataclass
class HookCommand:
    type: str
    command: str = ''
    prompt: str = ''
    url: str = ''
    if_: str = ''
    shell: str = DEFAULT_HOOK_SHELL
    timeout: float | None = None
    status_message: str = ''
    once: bool = False
    async_: bool = False
    async_rewake: bool = False
    model: str = ''
    headers: dict = field(default_factory=dict)
    allowed_env_vars: list = field(default_factory=list)
    fn: object = None
    error_message: str = ''
    internal: bool = False


@dataclass
class IndividualHookConfig:
    event: str
    config: HookCommand
    matcher: str = '*'
    source: str = ''
    hook_id: str = ''


@dataclass
class HookBlockingError:
    blocking_error: str
    command: str


@dataclass
class HookResult:
    hook: IndividualHookConfig
    outcome: str
    message: str = ''
    system_message: str = ''
    blocking_error: HookBlockingError | None = None
    suppress_output: bool = False
    stdout: str = ''
    stderr: str = ''
    exit_code: int = 0
    duration_ms: int = 0
    decision: str = ''
    additional_context: str = ''
    updated_input: dict | None = None
    initial_user_message: str = ''
    retry: bool = False


@dataclass
class AggregatedHookResult:
    results: list = field(default_factory=list)
    decision: str = ''
    continue_loop: bool = True
    suppress_output: bool = False
    blocking_error: HookBlockingError | None = None
    additional_context: str = ''
    updated_input: dict | None = None
    total_duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.blocking_error is None and not any(
            r.outcome == 'blocking' for r in self.results)


def get_hook_display_text(hook) -> str:
    if hook.status_message:
        return hook.status_message
    if hook.type == 'command':
        return hook.command
    if hook.type == 'prompt':
        return hook.prompt
    if hook.type == 'agent':
        return hook.prompt
    if hook.type == 'http':
        return hook.url
    return hook.type
