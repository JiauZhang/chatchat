from __future__ import annotations

import dataclasses

LEVELS = ("off", "low", "medium", "high", "xhigh")


@dataclasses.dataclass(frozen=True)
class Thinking:
    level: str = "medium"
    native: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"thinking level must be one of {LEVELS}, not {self.level!r}")

    @property
    def enabled(self) -> bool:
        return self.level != "off"

    def label(self) -> str:
        return f"thinking {self.level}" if self.enabled else "thinking off"
