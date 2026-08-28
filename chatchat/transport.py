from __future__ import annotations

import aiohttp

from chatchat.exceptions import APIError


# ---------------------------------------------------------------------------
# Global singleton transport. The whole process owns exactly one aiohttp
# session / TCP connector; every provider shares it. Per-request params
# (full url, timeout, proxy, api_key-as-header) are passed at call time, so
# the session never caches base_url / key / timeout.
# ---------------------------------------------------------------------------

_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    """Return the shared session, creating it lazily on first use."""
    global _session
    if _session is None:
        _session = aiohttp.ClientSession()
    return _session


async def close_transport() -> None:
    """Close the shared session if open. Idempotent; safe to call any time."""
    global _session
    if _session is not None:
        await _session.close()
        _session = None


class Transport:
    """Per-client transport handle. Holds only client-specific metadata
    (name / emit callback); the HTTP session is the global one. `stream` is a
    pure transport primitive: it yields raw SSE lines and performs NO business
    parsing — it receives the full url and headers per call."""

    def __init__(self, *, name, emit):
        self._name = name
        self._emit = emit

    async def close(self):
        # The session is global and owned by the runtime; nothing per-client
        # to close here.
        pass

    async def stream(self, url, payload, headers, timeout=None, proxy=None):
        session = get_session()
        async with session.post(
            url, json=payload, headers=headers, proxy=proxy, timeout=timeout,
        ) as response:
            if response.status == 429:
                raise _RetryableError("HTTP 429 rate limited")
            if response.status >= 500:
                raise _RetryableError(f"HTTP {response.status} server error")
            if response.status >= 400:
                text = await response.text()
                if self._emit:
                    await self._emit("client:error", {
                        "status_code": response.status,
                        "error": text[:500],
                    })
                raise APIError(f"API request failed: {response.status} {text}")
            async for line in response.content:
                if not line:
                    continue
                line = line.decode("utf-8", errors="ignore")
                if line.startswith("data:"):
                    yield line[len("data:"):].strip()


class _RetryableError(Exception):
    pass
