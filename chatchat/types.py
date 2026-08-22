from __future__ import annotations
from dataclasses import dataclass, field


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

    def __add__(self, other: 'Usage') -> 'Usage':
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def __iadd__(self, other: 'Usage') -> 'Usage':
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        return self


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
                self.tool_calls.append(ToolCall(
                    index=tc.index, id=tc.id, name=tc.name,
                    arguments=tc.arguments,
                ))
            else:
                if tc.id:
                    target.id = tc.id
                if tc.name and not target.name:
                    target.name = tc.name
                if tc.arguments:
                    target.arguments += tc.arguments

    def to_dict(self) -> dict:
        d = {'role': self.role, 'content': self.content}
        if self.tool_calls:
            d['tool_calls'] = [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {'name': tc.name, 'arguments': tc.arguments},
                }
                for tc in self.tool_calls
            ]
        return d


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
    usage: Usage = field(default_factory=Usage)


