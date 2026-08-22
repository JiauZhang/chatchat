from __future__ import annotations

import aiohttp

from chatchat.exceptions import APIError


class _RetryableError(Exception):
    pass


class Transport:
    """HTTP 传输层：负责一次 OpenAI 兼容的后端调用与 SSE 行抽取。

    职责单一——只有连接、鉴权、状态码处理、SSE `data:` 行剥离；不涉及补全语义。
    """

    def __init__(self, *, name, base_url, api_key, timeout, proxy, notify_429, emit):
        self._name = name
        self.base_url = base_url
        self._api_key = api_key
        self._notify_429 = notify_429
        self._emit = emit
        self._timeout = timeout
        self._proxy = proxy
        self._session = None

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def stream(self, url, payload):
        """单次请求，逐行产出剥离了 `data:` 前缀的 SSE 内容。

        429/5xx 抛 _RetryableError 供上层重试；4xx 直接抛 APIError。
        """
        session = self._get_session()
        full_url = self.base_url.rstrip('/') + url
        headers = {'Authorization': f'Bearer {self._api_key}'}
        async with session.post(full_url, json=payload, headers=headers,
                                proxy=self._proxy) as response:
            if response.status == 429:
                await self._notify_429()
                raise _RetryableError('HTTP 429 rate limited')
            if response.status >= 500:
                raise _RetryableError(f'HTTP {response.status} server error')
            if response.status >= 400:
                text = await response.text()
                await self._emit('client:error', {
                    'status_code': response.status,
                    'error': text[:500],
                })
                raise APIError(f'API request failed: {response.status} {text}')
            async for line in response.content:
                if not line:
                    continue
                line = line.decode('utf-8', errors='ignore')
                if line.startswith('data:'):
                    yield line[len('data:'):].strip()