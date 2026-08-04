from .version import __version__
from .scheduler import Scheduler, TimeoutError
from .message import ID, Message
from .worker import Worker, WorkerConfig
from .team import Team, TeamConfig


class ChatChatError(Exception):
    pass


class ConfigError(ChatChatError):
    pass


class ProviderError(ChatChatError):
    pass


class APIError(ChatChatError):
    pass