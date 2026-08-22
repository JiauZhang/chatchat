from __future__ import annotations

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass
from importlib import import_module

import aiohttp

from chatchat.config import load_config
from chatchat.providers import __providers__
from chatchat.rate_limiter import get_rate_limiter
from chatchat.runtime import Event, get_runtime
from chatchat.exceptions import ProviderError, APIError
from chatchat.tool import Tools
from chatchat.transport import Transport, _RetryableError
from chatchat.types import (
    ChatCompletionChunk,
    ChunkChoice,
    Delta,
    Message,
    ToolCall,
    Usage,
)


@dataclass
class ClientConfig:
    name: str = 'unknown'
    provider: str | None = None
    model: str | None = None
    instruction: str = ''
    http_options: dict | None = None


class BaseClient:
    base_url = ''
    max_retries = 3
    retry_backoff = 1.0

    def __init__(self, config: ClientConfig):
        self.config = config
        self.name = config.name
        self.provider = config.provider
        self._instruction = config.instruction
        self.model = config.model
        self.api_key = load_config(self.provider)
        self._rate_limiter = get_rate_limiter(self.provider)
        self.messages = []
        self.latest = None
        self.latest_usage = None
        opts = config.http_options or {}
        self._transport = Transport(
            name=self.name,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=aiohttp.ClientTimeout(total=opts.get('timeout') or 60.0),
            proxy=opts.get('proxy'),
            notify_429=self._rate_limiter.notify_429,
            emit=self._emit,
        )

    async def close(self):
        await self._transport.close()

    def clear(self):
        self.messages = []
        self.latest = None
        self.latest_usage = None

    async def _emit(self, topic: str, data: dict = None):
        await get_runtime().publish(Event(
            topic=f'lifecycle:{topic}', source=self.name, data=data or {},
        ))

    async def _send_streaming(self, url, payload):
        retries = 0
        started = False
        while True:
            try:
                async for line in self._transport.stream(url, payload):
                    started = True
                    yield line
                return
            except (aiohttp.ClientError, asyncio.TimeoutError, _RetryableError) as e:
                msg = f'{type(e).__name__}: {e}'
                if started or retries >= self.max_retries:
                    await self._emit('client:error', {'error': msg})
                    raise APIError(f'API request failed: {msg}') from e
                retries += 1
                await self._emit('client:retry', {'retry': retries, 'error': msg})
                await asyncio.sleep(min(self.retry_backoff * 2 ** retries, 8))

    def _build_request_body(self, model, messages, thinking, tools, **kwargs):
        if self._instruction:
            system_msg = {'role': 'system', 'content': self._instruction}
            messages = [system_msg] + messages
        payload = {
            'model': model or self.model,
            'messages': messages,
            'stream': True,
        }
        if thinking:
            payload['thinking'] = {'enabled': True}
        if tools:
            if isinstance(tools, Tools):
                payload['tools'] = tools.to_dict()
            else:
                payload['tools'] = tools
        payload.update(kwargs)
        return payload

    @staticmethod
    def _to_usage(data: dict) -> Usage:
        return Usage(
            prompt_tokens=data.get('prompt_tokens', 0),
            completion_tokens=data.get('completion_tokens', 0),
            total_tokens=data.get('total_tokens', 0),
        )

    def _to_tool_call(self, data: dict) -> ToolCall:
        func = data.get('function', {})
        return ToolCall(
            index=data.get('index', 0),
            id=data.get('id', ''),
            name=func.get('name', ''),
            arguments=func.get('arguments', ''),
        )

    def _to_delta(self, data: dict) -> Delta:
        return Delta(
            content=data.get('content', ''),
            reasoning_content=data.get('reasoning_content', ''),
            tool_calls=[self._to_tool_call(tc) for tc in (data.get('tool_calls') or [])],
        )

    def _to_chunk_choice(self, data: dict) -> ChunkChoice:
        return ChunkChoice(
            index=data.get('index', 0),
            delta=self._to_delta(data.get('delta', {})),
            finish_reason=data.get('finish_reason'),
        )

    def _to_chat_completion_chunk(self, data: dict) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=data.get('id', ''),
            object=data.get('object', 'chat.completion.chunk'),
            created=data.get('created', 0),
            model=data.get('model', ''),
            choices=[self._to_chunk_choice(c) for c in (data.get('choices') or [])],
            usage=self._to_usage(data.get('usage') or {}),
        )

    async def chat(self, messages, *, model=None, thinking=False, tools=None, **kwargs):
        self.latest = None
        self.latest_usage = None
        full = self.messages + messages
        payload = self._build_request_body(
            model=model, messages=full, thinking=thinking, tools=tools, **kwargs,
        )
        url = '/chat/completions'
        await self._emit('client:start', {'payload': payload})
        response_msg = Message()
        total_tokens = 0
        await self._rate_limiter.acquire()
        try:
            async for line in self._send_streaming(url, payload):
                if line.strip() == '[DONE]':
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = self._to_chat_completion_chunk(data)
                if chunk.usage.total_tokens:
                    total_tokens = chunk.usage.total_tokens
                    self.latest_usage = chunk.usage
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta:
                    response_msg.accumulate(delta)
                await self._emit('client:step', chunk)
                yield chunk
            self.latest = response_msg
            self.messages = full + [response_msg.to_dict()]
            await self._emit('client:end')
            await self._emit('client:tokens', {'usage': self.latest_usage})
        finally:
            await self._rate_limiter.release(total_tokens)


_supported_providers = sorted(
    p.stem for p in Path(__file__).parent.joinpath('providers').glob('*.py')
    if p.stem != '__init__'
)


def dynamic_import_client(provider):
    if provider not in __providers__ and provider in _supported_providers:
        import_module(f'chatchat.providers.{provider}')
    if provider in __providers__:
        return __providers__[provider]
    raise ProviderError(
        f'Provider `{provider}` is not supported. '
        f'Supported providers: {_supported_providers}'
    )


def create_client(config: ClientConfig) -> BaseClient:
    client_class = dynamic_import_client(config.provider)
    return client_class(config)