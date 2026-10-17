from chatchat.hooks.logger import install_default_logger, install_runtime_print
from chatchat.hooks.events import set_all_hook_events_enabled

install_default_logger()
install_runtime_print()
set_all_hook_events_enabled(True)
