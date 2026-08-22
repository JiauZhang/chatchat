class ChatChatError(Exception):
    pass


class ConfigError(ChatChatError):
    pass


class ProviderError(ChatChatError):
    pass


class APIError(ChatChatError):
    pass


class SubAgentError(ChatChatError):
    pass


class MaxStepsError(ChatChatError):
    pass