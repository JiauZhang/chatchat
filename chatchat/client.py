import json
import httpx
from importlib import import_module
from typing import Generator, Literal, overload

from chatchat.config import load_config
from chatchat.providers import __providers__
from chatchat import ProviderError, APIError
from chatchat.rate_limiter import get_rate_limiter
from chatchat.types import (
    ChatCompletion,
    ChatCompletionChunk,
    Choice,
    ChunkChoice,
    Delta,
    Message,
    ToolCall,
    Usage,
)


class BaseClient:
    def __init__(self, base_url, model=None, instruction=None,
                 http_options=None, event_bus=None):
        self._source = 'unknown'
        http_options = http_options or {}
        http_options.setdefault('timeout', 60.0)
        self._instruction = instruction
        self.api_key = load_config(self.provider)
        self.model = model
        self._bus = event_bus
        self.client = httpx.Client(
            base_url=base_url,
            **http_options,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )
        self.base_url = self.client.base_url
        self.headers = self.client.headers
        self.messages = [] if instruction is None else [self._system_message()]

        self._role_key = 'role'
        self._reasoning_content_key = 'reasoning_content'
        self._content_key = 'content'
        self._tool_calls_key = 'tool_calls'
        self._tool_call_index_key = 'index'
        self._tool_call_id_key = 'id'

        self._rate_limiter = get_rate_limiter(self.provider)

    def _system_message(self):
        return {'role': 'system', 'content': self._instruction}

    def _to_provider_format(self, messages):
        return messages

    def _to_openai_format(self, msg: Message) -> dict:
        d = {'role': msg.role}
        if msg.content:
            d['content'] = msg.content
        if msg.reasoning_content:
            d['reasoning_content'] = msg.reasoning_content
        if msg.tool_calls:
            d['tool_calls'] = [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.name,
                        'arguments': tc.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return d

    def _build_request_body(self, *, model, messages, stream=False, thinking=False, tools=None, **kwargs):
        payload = {
            'model': model if model else self.model,
            'messages': messages,
            **kwargs,
        }
        if thinking:
            payload['thinking'] = {'type': 'enabled'}
        if stream:
            payload['stream'] = True
        if tools:
            payload['tools'] = tools.to_dict()
        return payload

    def _to_tool_call(self, data: dict) -> ToolCall:
        func = data.get('function', {})
        return ToolCall(
            index=data.get('index', 0),
            id=data.get('id', ''),
            name=func.get('name', ''),
            arguments=func.get('arguments', ''),
        )

    def _to_message(self, data: dict) -> Message:
        reasoning = data.get(self._reasoning_content_key) or data.get('reasoning_content')
        return Message(
            role=data.get('role', 'assistant'),
            content=data.get('content', '') or '',
            tool_calls=[self._to_tool_call(tc) for tc in (data.get('tool_calls') or [])],
            reasoning_content=reasoning or '',
        )

    def _to_choice(self, data: dict) -> Choice:
        return Choice(
            index=data.get('index', 0),
            message=self._to_message(data.get('message', {})),
            finish_reason=data.get('finish_reason', ''),
        )

    def _to_chat_completion(self, data: dict) -> ChatCompletion:
        usage_data = data.get('usage') or {}
        usage = Usage(**{
            k: v for k, v in usage_data.items()
            if k in Usage.__dataclass_fields__
        })
        return ChatCompletion(
            id=data.get('id', ''),
            object=data.get('object', 'chat.completion'),
            created=data.get('created', 0),
            model=data.get('model', ''),
            choices=[self._to_choice(c) for c in (data.get('choices') or [])],
            usage=usage,
        )

    def _to_delta(self, data: dict) -> Delta:
        reasoning = data.get(self._reasoning_content_key) or data.get('reasoning_content')
        return Delta(
            role=data.get('role', ''),
            content=data.get('content', '') or '',
            tool_calls=[self._to_tool_call(tc) for tc in (data.get('tool_calls') or [])],
            reasoning_content=reasoning or '',
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

    def _emit(self, topic: str, data: dict = None):
        if self._bus:
            self._bus.emit(topic, data or {}, source=self._source)

    def _get_provider_message(self, data: dict) -> dict:
        return data['choices'][0]['message']

    def _send_nonstreaming(self, url, payload):
        self._rate_limiter.acquire()
        data = None
        try:
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._rate_limiter.notify_429()
            raise APIError(
                f'API request failed: {e.response.status_code} '
                f'{e.response.text}'
            )
        except httpx.RequestError as e:
            raise APIError(f'Network error: {e}')
        finally:
            if data is not None:
                usage = data.get('usage', {})
                total = usage.get('total_tokens', 0) if isinstance(usage, dict) else 0
            else:
                total = 0
            self._rate_limiter.release(actual_tokens=total)

        if 'error' in data:
            raise APIError(f'API error: {data["error"]}')

        return data

    def _send_streaming(self, url, payload):
        self._rate_limiter.acquire()
        try:
            with self.client.stream('POST', url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith('data: '):
                        continue
                    chunk = line[6:]
                    if chunk == '[DONE]':
                        break
                    try:
                        data = json.loads(chunk)
                    except Exception as e:
                        raise APIError(
                            f'Failed to parse SSE chunk: {e}\nData: {chunk}'
                        )
                    yield data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                self._rate_limiter.notify_429()
            raise APIError(
                f'Stream request failed: {e.response.status_code} '
            )
        except httpx.RequestError as e:
            raise APIError(f'Network error during streaming: {e}')
        finally:
            self._rate_limiter.release()

    @overload
    def chat(self, messages, *, model=None,
                      stream: Literal[False] = False,
                      thinking=False, tools=None,
                      **kwargs) -> ChatCompletion: ...
    @overload
    def chat(self, messages, *, model=None,
                      stream: Literal[True] = True,
                      thinking=False, tools=None,
                      **kwargs) -> Generator[ChatCompletionChunk, None, None]: ...

    def chat(self, messages, *, model=None, stream=False,
             thinking=False, tools=None, **kwargs):
        converted = self._to_provider_format(messages)
        full = self.messages + converted
        payload = self._build_request_body(
            model=model, messages=full, stream=stream, thinking=thinking, tools=tools, **kwargs,
        )
        url = '/chat/completions'
        self._emit('client:start', {'payload': payload})
        if not stream:
            return self._nonstream_chat(url, payload, full)
        return self._chat_stream(url, payload, full)

    def _nonstream_chat(self, url, payload, full):
        try:
            raw = self._send_nonstreaming(url, payload)
        except Exception as e:
            self._emit('client:error', {'error': str(e)})
            raise
        reply = self._get_provider_message(raw)
        self.messages = full + [reply]
        self._emit('client:step', {'response': raw})
        self._emit('client:end', {'response': raw})
        return self._to_chat_completion(raw)

    def _chat_stream(self, url, payload, full):
        acc = Message()
        step = 0
        try:
            for raw in self._send_streaming(url, payload):
                chunk = self._to_chat_completion_chunk(raw)
                if not chunk.choices:
                    continue
                acc.accumulate(chunk.choices[0].delta)
                step += 1
                delta = chunk.choices[0].delta
                self._emit('client:step', {
                    'delta': {
                        'content': delta.content or '',
                        'tool_calls': [{'index': tc.index, 'id': tc.id, 'name': tc.name, 'arguments': tc.arguments} for tc in delta.tool_calls],
                    },
                })
                yield chunk
        except Exception as e:
            self._emit('client:error', {'error': str(e)})
            raise
        reply = self._to_openai_format(acc)
        self.messages = full + self._to_provider_format([reply])
        self._emit('client:end')

    def clear(self):
        self.messages = [self._system_message()] if self._instruction else []


def dynamic_import_client(provider):
    if provider in __providers__:
        return __providers__[provider]
    try:
        import_module(f'chatchat.providers.{provider}')
    except ImportError:
        pass
    if provider in __providers__:
        return __providers__[provider]
    raise ProviderError(
        f'Provider `{provider}` is not supported. '
        f'Supported providers: {list(__providers__.keys())}'
    )


class Client:
    """非 Actor 的 LLM 客户端，直接封装 BaseClient 调用。

    Client 仅作为 Agent 内部组件使用，不存在并发问题，无需 mailbox 线程。
    """
    def __init__(self, provider, model, instruction=None, http_options=None, event_bus=None, source='unknown'):
        client_class = dynamic_import_client(provider)
        self.client: BaseClient = client_class(
            model=model, instruction=instruction, http_options=http_options,
            event_bus=event_bus,
        )
        self.client._source = source

    def chat(self, messages, *, model=None, stream=False, thinking=False, tools=None, **kwargs):
        return self.client.chat(
            messages,
            model=model, stream=stream, thinking=thinking, tools=tools,
            **kwargs,
        )

    def clear(self):
        self.client.clear()

    @property
    def messages(self):
        return self.client.messages

    @messages.setter
    def messages(self, value):
        self.client.messages = value

    @property
    def instruction(self):
        return self.client._instruction