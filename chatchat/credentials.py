from __future__ import annotations

import json
import os
from pathlib import Path


def get_secret_file() -> Path:
    return Path(os.environ.get("CHATCHAT_SECRET_FILE", "~/.chatchat/config.json")).expanduser()


def _profile_entry(provider: str) -> dict:
    path = get_secret_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    if isinstance(data, dict) and isinstance(data.get(provider), dict):
        return dict(data[provider])
    return {}


def get_provider_profile(provider: str) -> dict:
    env = f"CHATCHAT_{provider.upper()}_"
    entry = _profile_entry(provider)
    hint = f"请在 config 文件（{get_secret_file()}）的 {provider} 条目中配置，或用 CHATCHAT_{provider.upper()}_ 环境变量。"

    def missing(field: str) -> RuntimeError:
        return RuntimeError(f'Provider "{provider}" 未配置 {field}。{hint}')

    protocol_type = (os.environ.get(env + "TYPE") or entry.get("type") or "").strip().lower()
    if not protocol_type:
        raise missing("type")
    base_url = os.environ.get(env + "BASE_URL") or entry.get("base_url")
    if not base_url:
        raise missing("base_url")
    api_key = os.environ.get(env + "API_KEY") or entry.get("api_key")
    if not api_key:
        raise missing("api_key")
    return {"type": protocol_type, "base_url": base_url, "api_key": api_key}


def get_rate_limits() -> dict:
    """Per-provider rpm limits, declared next to the profiles that use them."""
    path = get_secret_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    limits = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        try:
            rpm = int(entry.get("rpm"))
        except (TypeError, ValueError):
            continue
        if rpm > 0:
            limits[str(name)] = rpm
    return limits
