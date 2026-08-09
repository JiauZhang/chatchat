from .version import __version__
from .scheduler import Scheduler, TimeoutError
from .message import Message, make_id
from .agent import Agent, AgentConfig, BaseAgentConfig, create_agent
from .team import Team, TeamConfig, create_team


class ChatChatError(Exception):
    pass


class ConfigError(ChatChatError):
    pass


class ProviderError(ChatChatError):
    pass


class APIError(ChatChatError):
    pass