from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class Metrics:
    tool_calls: int = 0
    tool_ms: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    api_ms: int = 0
    requests: int = 0
    hooks: int = 0
    hook_ms: int = 0
    denials: int = 0

    def tool_ran(self, ms: int, *, added: int = 0, removed: int = 0) -> None:
        self.tool_calls += 1
        self.tool_ms += int(ms)
        self.lines_added += int(added)
        self.lines_removed += int(removed)

    def api_round(self, ms: int) -> None:
        self.requests += 1
        self.api_ms += int(ms)

    def hook_ran(self, ms: int) -> None:
        self.hooks += 1
        self.hook_ms += int(ms)

    def refused(self) -> None:
        self.denials += 1

    def __add__(self, other: 'Metrics') -> 'Metrics':
        return Metrics(**{field.name: getattr(self, field.name)
                          + getattr(other, field.name)
                          for field in dataclasses.fields(self)})

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)
