from __future__ import annotations

import random


def rand_name(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"
