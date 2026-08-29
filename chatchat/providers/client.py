from __future__ import annotations

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass, field
from importlib import import_module

import aiohttp

from chatchat.core.config import load_config
from chatchat.core.rate_limiter import RateLimit, ProviderLimiter
from chatchat.core.exceptions import ProviderError, APIError
from chatchat.providers import __providers__
from chatchat.tools.registry import Tools
from chatchat.core.transport import Transport, _RetryableError
from chatchat.providers.protocol import (
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
    rate_limit: RateLimit = field(default_factory=RateLimit)
    emit: Callable | None = None


class BaseClient:
    """Common provider client. Holds a Transport (global session) and a
    ProviderLimiter (per-provider RPM/TPM/concurrency). The `chat` main loop
    is defined once here; provider differences live in the hooks
    (_build_url / _build_headers / _build_request_body)."""
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
        self._limiter = ProviderLimiter(config.rate_limit)
        self.messages = []
        self.latest = None
        self.latest_usage = None
        self._emit_cb = config.emit
        self._transport = Transport(name=self.name, emit=self._emit)

    async def close(self):
        await self._transport.close()

    def clear(self):
        self.messages = []
        self.latest = None
        self.latest_usage = None

    async def _emit(self, topic: str, data: dict = None):
        if self._emit_cb is not None:
            await self._emit_cb(topic, data or {})

    # ----- hooks (overridden by provider subclasses) -----------------------
    def _build_url(self) -> str:
        return self.base_url.rstrip('/') + '/chat/completions'

    def _build_headers(self) -> dict:
        return {'Authorization': f'Bearer {self.api_key}'}

    async def _send_streaming(self, url, payload, headers):
        retries = 0
        started = False
        while True:
            try:
                async for line in self._transport.stream(url, payload, headers):
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
        url = self._build_url()
        headers = self._build_headers()
        await self._emit('client:start', {'payload': payload})
        response_msg = Message()
        total_tokens = 0
        async with self._limiter:  # concurrency + RPM admission
            try:
                async for line in self._send_streaming(url, payload, headers):
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
            finally:
                # account real token usage (TPM) from the structured result
                self._limiter.account(total_tokens)
                await self._emit('client:tokens', {'usage': self.latest_usage})


_provider_dir = Path(__file__).resolve().parent
_supported_providers = sorted(
    p.stem for p in _provider_dir.glob('*.py')
    if p.stem not in ('__init__', 'client', 'protocol')
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
