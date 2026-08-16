import json
from pathlib import Path
from dataclasses import dataclass

import httpx
from importlib import import_module
from typing import Generator

from chatchat.config import load_config
from chatchat.providers import __providers__
from chatchat.rate_limiter import get_rate_limiter
from chatchat.runtime import get_runtime
from chatchat.exceptions import ProviderError, APIError
from chatchat.tool import Tools
from chatchat.types import (
    ChatCompletionChunk,
    ChunkChoice,
    Delta,
    ToolCall,
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

    def __init__(self, config: ClientConfig):
        self.config = config
        self.name = config.name
        http_options = config.http_options or {}
        http_options.setdefault('timeout', 60.0)
        http_options.setdefault('follow_redirects', True)
        self._instruction = config.instruction
        self.api_key = load_config(self.provider)
        self.model = config.model
        self.client = httpx.Client(
            base_url=self.base_url,
            **http_options,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )
        self._messages = []
        self._rate_limiter = get_rate_limiter(self.provider)

    @property
    def messages(self):
        return self._messages

    @messages.setter
    def messages(self, value):
        self._messages = value

    def clear(self):
        self._messages = []

    def _emit(self, topic: str, data: dict = None):
        if data is not None and not isinstance(data, dict):
            data = data.__dict__
        get_runtime().emit(topic, data, name=self.name)

    def _to_provider_format(self, messages):
        return messages

    def _send_streaming(self, url, payload):
        self._rate_limiter.acquire()
        try:
            with self.client.stream('POST', url, json=payload) as response:
                if response.status_code == 429:
                    self._rate_limiter.notify_429()
                if response.status_code >= 400:
                    response.read()
                    self._emit('client:error', {
                        'status_code': response.status_code,
                        'error': response.text[:500],
                    })
                    raise APIError(
                        f'API request failed: {response.status_code} '
                        f'{response.text}'
                    )
                for line in response.iter_lines():
                    if line.startswith('data: '):
                        yield line[6:]
                    elif line.startswith('data:'):
                        yield line[5:]
        except httpx.RequestError as e:
            self._emit('client:error', {'error': str(e)})
            raise APIError(f'API request failed: {e}')
        finally:
            self._rate_limiter.release()

    def _to_provider_format(self, messages):
        """Convert messages to provider-specific format. Override in subclasses."""
        return messages

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
        )

    def chat(self, messages, *, model=None, thinking=False, tools=None, **kwargs):
        converted = self._to_provider_format(messages)
        full = self.messages + converted
        payload = self._build_request_body(
            model=model, messages=full, thinking=thinking, tools=tools, **kwargs,
        )
        url = '/chat/completions'
        self._emit('client:start', {'payload': payload})
        return self._chat_stream(url, payload, full)

    def _chat_stream(self, url, payload, messages):
        response_msg = {'role': 'assistant', 'content': ''}
        for line in self._send_streaming(url, payload):
            if line.strip() == '[DONE]':
                self._messages = messages + [response_msg]
                self._emit('client:end')
                return
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = self._to_chat_completion_chunk(data)
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                if delta.content:
                    response_msg['content'] += delta.content
                if delta.tool_calls:
                    self._accumulate_tool_calls(response_msg, delta.tool_calls)
            self._emit('client:step', chunk)
            yield chunk

    def _accumulate_tool_calls(self, response_msg: dict, tool_calls: list):
        if 'tool_calls' not in response_msg:
            response_msg['tool_calls'] = []
        for tc in tool_calls:
            while len(response_msg['tool_calls']) <= tc.index:
                response_msg['tool_calls'].append(
                    {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}}
                )
            entry = response_msg['tool_calls'][tc.index]
            if tc.id:
                entry['id'] = tc.id
            if tc.name:
                entry['function']['name'] = tc.name
            if tc.arguments:
                entry['function']['arguments'] += tc.arguments


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


class Client:
    def __init__(self, provider, model, instruction=None, name=None, http_options=None):
        config = ClientConfig(
            provider=provider, model=model,
            instruction=instruction or '',
            name=name or 'unknown',
            http_options=http_options,
        )
        client_class = dynamic_import_client(config.provider)
        self.client: BaseClient = client_class(config)

    @property
    def messages(self):
        return self.client.messages

    @messages.setter
    def messages(self, value):
        self.client.messages = value

    def clear(self):
        self.client.clear()

    def chat(self, messages, *, model=None, thinking=False, tools=None, **kwargs):
        return self.client.chat(
            messages,
            model=model, thinking=thinking, tools=tools,
            **kwargs,
        )