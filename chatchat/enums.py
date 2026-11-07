from __future__ import annotations

from enum import StrEnum


class ValueStrEnum(StrEnum):
    @classmethod
    def values(cls):
        return tuple(item.value for item in cls)
