import json
import httpx
from importlib import import_module
from typing import Generator, Literal, overload

from chatchat.config import load_config
from chatchat.providers import __providers__, __custom_providers__
from chatchat import ProviderError, APIError
from chatchat.types import (
    ChatCompletion,
    ChatCompletionChunk,
    Choice,
    ChunkChoice,
    Delta,
    Message,
    Progress,
    ProgressType,
    ToolCall,
    Usage,
)


class BaseClient:
    def __init__(self, provider, base_url, model=None, instruction=None, http_options=None):
        http_options = http_options or {}
        http_options.setdefault('timeout', 60.0)
        self.provider = provider
        self._instruction = instruction
        self.api_key = load_config(provider)
        self.model = model
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

    def _get_provider_message(self, data: dict) -> dict:
        return data['choices'][0]['message']

    def _send_nonstreaming(self, url, payload):
        try:
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f'API request failed: {e.response.status_code} '
                f'{e.response.text}'
            )
        except httpx.RequestError as e:
            raise APIError(f'Network error: {e}')

        if 'error' in data:
            raise APIError(f'API error: {data["error"]}')

        return data

    def _send_streaming(self, url, payload):
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
            raise APIError(
                f'Stream request failed: {e.response.status_code} '
            )
        except httpx.RequestError as e:
            raise APIError(f'Network error during streaming: {e}')

    @overload
    def chat(self, messages, *, model=None,
                      stream: Literal[False] = False,
                      thinking=False, tools=None, on_progress=None, step=0,
                      **kwargs) -> ChatCompletion: ...
    @overload
    def chat(self, messages, *, model=None,
                      stream: Literal[True] = True,
                      thinking=False, tools=None, on_progress=None, step=0,
                      **kwargs) -> Generator[ChatCompletionChunk, None, None]: ...

    def chat(self, messages, *, model=None, stream=False,
             thinking=False, tools=None, on_progress=None, step=0, **kwargs):
        converted = self._to_provider_format(messages)
        full = self.messages + converted
        payload = self._build_request_body(
            model=model, messages=full, stream=stream, thinking=thinking, tools=tools, **kwargs,
        )
        url = '/chat/completions'
        if on_progress:
            on_progress(Progress(type=ProgressType.CLIENT_START, step=step))
            on_progress(Progress(type=ProgressType.CLIENT_STEP, step=step))
        if not stream:
            return self._nonstream_chat(url, payload, full, on_progress=on_progress)
        return self._chat_stream(url, payload, full, on_progress=on_progress)

    def _nonstream_chat(self, url, payload, full, on_progress=None):
        try:
            raw = self._send_nonstreaming(url, payload)
        except Exception as e:
            if on_progress:
                on_progress(Progress(type=ProgressType.CLIENT_ERROR, content=str(e)))
            raise
        reply = self._get_provider_message(raw)
        self.messages = full + [reply]
        if on_progress:
            on_progress(Progress(type=ProgressType.CLIENT_END))
        return self._to_chat_completion(raw)

    def _chat_stream(self, url, payload, full, on_progress=None):
        acc = Message()
        try:
            for raw in self._send_streaming(url, payload):
                chunk = self._to_chat_completion_chunk(raw)
                if not chunk.choices:
                    continue
                acc.accumulate(chunk.choices[0].delta)
                yield chunk
        except Exception as e:
            if on_progress:
                on_progress(Progress(type=ProgressType.CLIENT_ERROR, content=str(e)))
            raise
        reply = self._to_openai_format(acc)
        self.messages = full + self._to_provider_format([reply])
        if on_progress:
            on_progress(Progress(type=ProgressType.CLIENT_END))

    def clear(self):
        self.messages = [self._system_message()] if self._instruction else []


def dynamic_import_client(provider):
    if provider in __custom_providers__:
        return __custom_providers__[provider]
    if provider not in __providers__:
        name_list = list(__custom_providers__) + list(__providers__)
        raise ProviderError(
            f'Provider `{provider}` is not supported. '
            f'Supported providers: {name_list}'
        )
    client_module = import_module(f'chatchat.providers.{provider}')
    client_class = getattr(client_module, f'{provider.capitalize()}Client')
    return client_class


class Client:
    def __init__(self, provider, model, instruction=None, http_options=None):
        client_class = dynamic_import_client(provider)
        self.client: BaseClient = client_class(
            model=model, instruction=instruction, http_options=http_options,
        )

    @overload
    def chat(self, messages, *, model=None, stream: Literal[False] = False,
        thinking=False, tools=None, on_progress=None, step=0,
        **kwargs) -> ChatCompletion: ...
    @overload
    def chat(self, messages, *, model=None, stream: Literal[True] = True,
        thinking=False, tools=None, on_progress=None, step=0,
        **kwargs) -> Generator[ChatCompletionChunk, None, None]: ...

    def chat(self, messages, *, model=None, stream=False,
             thinking=False, tools=None, on_progress=None, step=0, **kwargs):
        return self.client.chat(
            messages, model=model, stream=stream, thinking=thinking,
            tools=tools, on_progress=on_progress, step=step, **kwargs,
        )

    def clear(self):
        self.client.clear()

    @property
    def messages(self):
        return self.client.messages

    @property
    def instruction(self):
        return self.client._instruction