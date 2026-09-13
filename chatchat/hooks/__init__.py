from chatchat.hooks.events import (HOOK_EVENTS, register_hook_event_handler,
                                   set_all_hook_events_enabled)
from chatchat.hooks.logger import install_default_logger, install_runtime_print
from chatchat.hooks.manager import HookManager
from chatchat.hooks.settings import get_all_hooks, register_builtin

install_default_logger()
install_runtime_print()
set_all_hook_events_enabled(True)
