from __future__ import annotations


class Sandbox:
    """Where a sub-agent runs when it must not touch the checked-out tree.

    The runtime does not know how to make such a workspace - that needs a
    version control system, or whatever the host uses instead - so it is handed
    a provider that can start one and give it back, plus the options the host
    offers. Nothing is reserved when there is no provider, and the caller is
    told so.
    """

    def __init__(self, start=None, end=None, options=()):
        self.start = start
        self.end = end
        self.options = tuple(options)
        self._reserved: dict[str, str] = {}

    def available(self) -> bool:
        return self.start is not None

    def supports(self, name: str) -> bool:
        return any(str(option.get("value") or "") == name for option in self.options)

    async def reserve(self, name: str, agent_id: str) -> str:
        if self.start is None:
            raise ValueError("sandbox needs a provider: this run was given no sandbox provider")
        path = str(await self.start(name))
        self._reserved[agent_id] = path
        return path

    async def release(self, agent_id: str) -> str:
        path = self._reserved.pop(agent_id, None)
        if path is None or self.end is None:
            return ""
        return str(await self.end(path))
