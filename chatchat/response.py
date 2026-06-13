from dataclasses import dataclass, field
from typing import Generator


@dataclass
class ToolCall:
    index: int = 0
    id: str = ''
    name: str = ''
    arguments: str = ''


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Message:
    role: str = 'assistant'
    content: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ''

    def accumulate(self, delta: 'Delta'):
        if delta.role:
            self.role = delta.role
        if delta.content:
            self.content += delta.content
        if delta.reasoning_content:
            self.reasoning_content += delta.reasoning_content
        for tc in delta.tool_calls:
            target = None
            for existing in self.tool_calls:
                if existing.index == tc.index:
                    target = existing
                    break
            if target is None:
                self.tool_calls.append(tc)
            else:
                if tc.id:
                    target.id = tc.id
                if tc.name:
                    target.name += tc.name
                if tc.arguments:
                    target.arguments += tc.arguments


@dataclass
class Choice:
    index: int = 0
    message: Message = field(default_factory=Message)
    finish_reason: str = ''


@dataclass
class ChatCompletion:
    id: str = ''
    object: str = 'chat.completion'
    created: int = 0
    model: str = ''
    choices: list[Choice] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class Delta:
    role: str = ''
    content: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ''


@dataclass
class ChunkChoice:
    index: int = 0
    delta: Delta = field(default_factory=Delta)
    finish_reason: str | None = None


@dataclass
class ChatCompletionChunk:
    id: str = ''
    object: str = 'chat.completion.chunk'
    created: int = 0
    model: str = ''
    choices: list[ChunkChoice] = field(default_factory=list)


