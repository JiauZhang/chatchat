from __future__ import annotations

from chatchat.runtime.thinking import Thinking
from chatchat.protocols import Delta, ToolCall, get_protocol  # noqa: F401

import asyncio
import json
import os
from dataclasses import dataclass, field
from inspect import signature
from pathlib import Path
from typing import Optional

import aiohttp


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
                t.arguments = t.arguments if _is_json(t.arguments) \
                    else t.arguments + tc.arguments


def _is_json(s: str) -> bool:
    try:
        json.loads(s)
    except (ValueError, TypeError):
        return False
    return True


OFFICIAL_BASE_URLS = {'openai': 'https://api.openai.com/v1',
                      'anthropic': 'https://api.anthropic.com'}


def secret_file() -> Path:
    return Path(os.environ.get('CHATCHAT_SECRET_FILE',
                               '~/.chatchat.json')).expanduser()


def _default_secret_paths():
    chatchat_home = Path(os.environ.get('CHATCHAT_HOME',
                                        '~/.chatchat')).expanduser()
    return [secret_file(), chatchat_home / 'chatchat.json']


def _profile_entry(provider: str) -> dict:
    for f in _default_secret_paths():
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get(provider), dict):
            return dict(data[provider])
    return {}


def load_profile(provider: str) -> dict:
    env = f'CHATCHAT_{provider.upper()}_'
    entry = _profile_entry(provider)
    protocol_type = (os.environ.get(env + 'TYPE')
                 or entry.get('type') or '').strip().lower()
    if not protocol_type:
        protocol_type = 'anthropic' if provider == 'anthropic' else 'openai'
    if protocol_type not in ('openai', 'anthropic'):
        raise RuntimeError(
            f'Provider "{provider}" 的 type 必须是 openai 或 anthropic，'
            f'不是 {protocol_type!r}。')
    base_url = (os.environ.get(env + 'BASE_URL')
                or entry.get('base_url')
                or OFFICIAL_BASE_URLS.get(provider, ''))
    if not base_url:
        raise RuntimeError(
            f'Provider "{provider}" 未配置 base_url。'
            f'请在配置文件的 {provider} 条目中添加 base_url，'
            f'或设置 CHATCHAT_{provider.upper()}_BASE_URL。'
            f'保留名 openai / anthropic 可省略 base_url。')
    api_key = os.environ.get(env + 'API_KEY') or entry.get('api_key')
    if not api_key:
        raise RuntimeError(
            f'Provider "{provider}" 未配置 api_key。'
            f'请设置 CHATCHAT_{provider.upper()}_API_KEY '
            f'或在 ~/.chatchat.json / ~/.chatchat/chatchat.json 的 '
            f'{provider} 下配置。')
    return {'type': protocol_type, 'base_url': base_url, 'api_key': api_key}


class Client:

    def __init__(self, provider, model, instruction=None, http_options={},
                 thinking: Thinking = Thinking()):
        self.provider = provider
        self.model = model
        self.instruction = instruction
        self.thinking = thinking
        profile = load_profile(provider)
        self.base_url = profile['base_url']
        self.api_key = profile['api_key']
        self._protocol = get_protocol(profile['type'])
        self._headers = self._protocol.headers(self.api_key)
        self._timeout = aiohttp.ClientTimeout(total=(http_options or {}).get('timeout', 120))

    def _messages(self, messages):
        if self.instruction:
            messages = [{'role': 'system', 'content': self.instruction}] + messages
        return messages

    async def respond(self, messages: list[dict], tools: Optional[list[dict]] = None,
                      *, stream_cb=None):
        msgs = self._messages(messages)
        payload = self._protocol.payload(msgs, tools, self.model, self.thinking)
        aggregated = Message()
        self._last_usage = Usage()
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(self._protocol.endpoint(self.base_url),
                                    json=payload, headers=self._headers) as resp:
                resp.raise_for_status()
                async for line in resp.content:
                    usage, deltas = self._protocol.parse(line)
                    if usage:
                        self._last_usage.add(Usage.from_dict(usage))
                    for delta in deltas:
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
