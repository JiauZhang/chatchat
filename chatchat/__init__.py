from .version import __version__
from .task import Task, TaskStatus


class ChatChatError(Exception):
    pass


class ConfigError(ChatChatError):
    pass


class ProviderError(ChatChatError):
    pass


class APIError(ChatChatError):
    pass