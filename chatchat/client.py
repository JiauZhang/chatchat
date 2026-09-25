from __future__ import annotations

from chatchat.runtime.thinking import Thinking

import asyncio
import json
import os
from dataclasses import dataclass, field
from importlib import import_module
from inspect import signature
from pathlib import Path
from typing import Optional

import aiohttp

from chatchat.providers import get_provider, provider_names


@dataclass
class ToolUse:
    name: str
    input: dict
    id: str = ''


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_details: dict | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> 'Usage':
        if not d:
            return cls()
        details = d.get('prompt_tokens_details')
        return cls(
            prompt_tokens=int(d.get('prompt_tokens', 0) or 0),
            completion_tokens=int(d.get('completion_tokens', 0) or 0),
            total_tokens=int(d.get('total_tokens', 0) or 0),
            prompt_tokens_details=details if isinstance(details, dict) else None,
        )

    def add(self, other: 'Usage'):
        if other is None:
            return
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        if other.prompt_tokens_details:
            if self.prompt_tokens_details is None:
                self.prompt_tokens_details = {}
            for k, v in other.prompt_tokens_details.items():
                if isinstance(v, (int, float)):
                    self.prompt_tokens_details[k] = \
                        self.prompt_tokens_details.get(k, 0) + v

    def to_dict(self) -> dict:
        return {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'prompt_tokens_details': self.prompt_tokens_details,
        }


@dataclass
class ToolCall:
    index: int = 0
    id: str = ''
    name: str = ''
    arguments: str = ''


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


@dataclass
class Message:
    content: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ''

    def accumulate(self, delta: Delta):
        if delta.content:
            self.content += delta.content
        if delta.reasoning_content:
            self.reasoning_content += delta.reasoning_content
        for tc in delta.tool_calls:
            t = next((x for x in self.tool_calls if x.index == tc.index), None)
            if t is None:
                self.tool_calls.append(ToolCall(index=tc.index))
                t = self.tool_calls[-1]
            if tc.id:
                t.id = tc.id
            if tc.name and not t.name:
                t.name = tc.name
            if tc.arguments:
                t.arguments = tc.arguments if _is_json(t.arguments) else t.arguments + tc.arguments


def _is_json(s: str) -> bool:
    try:
        json.loads(s)
    except (ValueError, TypeError):
        return False
    return True


def to_openai(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        c = m.get('content')
        if isinstance(c, list) and c:
            if m.get('role') == 'assistant':
                calls = [{'id': t.get('id'), 'type': 'function',
                          'function': {'name': t.get('name'),
                                       'arguments': json.dumps(t.get('input', {}))}}
                         for t in c if t.get('type') == 'tool_use']
                out.append({'role': 'assistant', 'content': None, 'tool_calls': calls})
            else:
                out += [{'role': 'tool', 'tool_call_id': t.get('tool_use_id'),
                         'content': t.get('content', '')} for t in c]
        else:
            out.append({'role': m.get('role', 'user'), 'content': c or ''})
    return out


def to_openai_tools(schemas: list[dict]) -> list[dict]:
    return [{'type': 'function', 'function': {
        'name': s['name'],
        'description': s.get('description', ''),
        'parameters': s.get('input_schema', {}),
    }} for s in schemas]


def secret_file() -> Path:
    return Path(os.environ.get('CHATCHAT_SECRET_FILE',
                               '~/.chatchat.json')).expanduser()


def _default_secret_paths():
    chatchat_home = Path(os.environ.get('CHATCHAT_HOME',
                                        '~/.chatchat')).expanduser()
    return [secret_file(), chatchat_home / 'chatchat.json']


def load_secret(provider: str) -> dict:
    env = os.environ.get(f'CHATCHAT_{provider.upper()}_API_KEY')
    if env:
        return {'api_key': env}
    for f in _default_secret_paths():
        if f.exists():
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            if isinstance(data, dict) and provider in data and isinstance(data[provider], dict):
                return dict(data[provider])
    return {}


def _to_chunk(ch: dict, model: str) -> ChunkChoice:
    d = ch.get('delta', {})
    tcs = [ToolCall(index=tc.get('index', 0), id=tc.get('id') or '',
                    name=(tc.get('function') or {}).get('name') or '',
                    arguments=(tc.get('function') or {}).get('arguments') or '')
           for tc in (d.get('tool_calls') or [])]
    delta = Delta(role=d.get('role') or '', content=d.get('content') or '',
                  reasoning_content=d.get('reasoning_content') or '', tool_calls=tcs)
    return ChunkChoice(delta=delta)


class BaseClient:

    def __init__(self, provider, base_url, model=None, instruction=None, http_options={}):
        self.provider = provider
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.instruction = instruction
        secret = load_secret(provider)
        if 'api_key' not in secret:
            raise RuntimeError(
                f'Provider "{provider}" 未配置 api_key。'
                f'请设置 CHATCHAT_{provider.upper()}_API_KEY '
                f'或在 ~/.chatchat.json / ~/.chatchat/chatchat.json 的 {provider} 下配置。')
        self.api_key = secret['api_key']
        self._extra = secret


def dynamic_import_client(provider):
    client_class = get_provider(provider)
    if client_class is None:
        raise RuntimeError(f'provider `{provider}` 不受支持，'
                           f'支持的 providers: {provider_names()}')
    return client_class


class Client:

    def __init__(self, provider, model, instruction=None, http_options={},
                 thinking: Thinking = Thinking()):
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.thinking = thinking
        spec = dynamic_import_client(provider)(
            model=model, instruction=instruction, http_options=http_options)
        self.base_url = spec.base_url
        self.api_key = spec.api_key
        self._headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        self._timeout = aiohttp.ClientTimeout(total=(http_options or {}).get('timeout', 120))

    def _messages(self, messages):
        if self.instruction:
            messages = [{'role': 'system', 'content': self.instruction}] + messages
        return messages

    async def respond(self, messages: list[dict], tools: Optional[list[dict]] = None,
                      *, stream_cb=None):
        msgs = self._messages(messages)
        tools_openai = to_openai_tools(tools) if tools else None
        payload = {'model': self.model, 'messages': to_openai(msgs), 'stream': True,
                   'stream_options': {'include_usage': True}}
        payload.update(self.thinking.request())
        if tools_openai:
            payload['tools'] = tools_openai
        aggregated = Message()
        self._last_usage = Usage()
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(self.base_url + '/chat/completions',
                                    json=payload, headers=self._headers) as resp:
                resp.raise_for_status()
                async for line in resp.content:
                    if not line:
                        continue
                    raw = line.strip()
                    if raw == b'[DONE]':
                        break
                    if raw.startswith(b'data:'):
                        raw = raw[5:].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if data.get('usage'):
                        self._last_usage = Usage.from_dict(data['usage'])
                    for choice in (data.get('choices') or []):
                        delta = _to_chunk(choice, self.model).delta
                        aggregated.accumulate(delta)
                        if stream_cb:
                            if delta.reasoning_content:
                                stream_cb(delta.reasoning_content, 'reason')
                            if delta.content and not delta.reasoning_content:
                                stream_cb(delta.content, 'text')
        if not aggregated.tool_calls:
            return aggregated.content
        outs = []
        for t in aggregated.tool_calls:
            try:
                inp = json.loads(t.arguments or '{}')
            except ValueError:
                inp = {}
                if stream_cb:
                    stream_cb(f'[warn] tool 参数解析失败: {t.arguments[:80]!r}', 'warn')
            outs.append(ToolUse(t.name, inp, t.id))
        return outs

    async def chat(self, text: str, *, model: str = None, history: Optional[list[dict]] = None,
                   tools: Optional[list[dict]] = None, stream_cb=None):
        messages = list(history or []) + [{'role': 'user', 'content': text}]
        resp = await self.respond(messages, tools=tools, stream_cb=stream_cb)
        if isinstance(resp, str):
            return resp
        return json.dumps([{'name': t.name, 'input': t.input} for t in resp], ensure_ascii=False)

    async def complete(self, prompt: str, *, stream_cb=None):
        return await self.respond([{'role': 'user', 'content': prompt}], stream_cb=stream_cb)


class MockClient:

    def __init__(self, handler=None, thinking: Thinking = Thinking(),
                 name: str = '',
                 usage=None, model: str = None):
        self._handler = handler
        self.thinking = thinking
        self.name = name
        self.model = model
        self._usage = usage
        self._last_usage = Usage()

    async def respond(self, messages: list[dict], tools: Optional[list[dict]] = None,
                      *, stream_cb=None):
        self._last_usage = Usage()
        if self._handler is not None:
            params = signature(self._handler).parameters
            out = self._handler(messages, tools, stream_cb=stream_cb) if (
                'stream_cb' in params) else self._handler(messages, tools)
            out = await out if asyncio.iscoroutine(out) else out
        else:
            out = 'ok'
        self._last_usage = Usage.from_dict(self._usage)
        return out
