import json
import os

import pytest

from chatchat.client import load_profile


def _secret_file(monkeypatch, tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("CHATCHAT_SECRET_FILE", str(path))
    return path


def _profile(name, **over):
    entry = {"type": "openai", "base_url": "https://api.example.com/v1", "api_key": "sk-1"}
    entry.update(over)
    return {name: entry}


def test_a_complete_profile_resolves_verbatim(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, _profile("agnes"))
    assert load_profile("agnes") == {"type": "openai", "base_url": "https://api.example.com/v1", "api_key": "sk-1"}


def test_an_anthropic_profile_carries_its_type(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, _profile("kimi", type="anthropic", base_url="https://api.moonshot.ai"))
    assert load_profile("kimi")["type"] == "anthropic"


def test_type_is_required(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {"agnes": {"base_url": "https://x.example/v1", "api_key": "sk-1"}})
    with pytest.raises(RuntimeError) as e:
        load_profile("agnes")
    assert "type" in str(e.value)


def test_base_url_is_required(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {"agnes": {"type": "openai", "api_key": "sk-1"}})
    with pytest.raises(RuntimeError) as e:
        load_profile("agnes")
    assert "base_url" in str(e.value)


def test_api_key_is_required(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {"agnes": {"type": "openai", "base_url": "https://x.example/v1"}})
    with pytest.raises(RuntimeError) as e:
        load_profile("agnes")
    assert "api_key" in str(e.value)


def test_an_unknown_type_is_refused(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {"agnes": {"type": "grpc", "base_url": "https://x.example", "api_key": "k"}})
    with pytest.raises(RuntimeError) as e:
        load_profile("agnes")
    assert "grpc" in str(e.value)


def test_env_overrides_beat_the_profile_entry(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, _profile("agnes"))
    monkeypatch.setenv("CHATCHAT_AGNES_API_KEY", "env-key")
    monkeypatch.setenv("CHATCHAT_AGNES_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("CHATCHAT_AGNES_TYPE", "anthropic")
    assert load_profile("agnes") == {"type": "anthropic", "base_url": "https://env.example/v1", "api_key": "env-key"}


def test_env_alone_can_serve_a_profile(monkeypatch, tmp_path):
    monkeypatch.delenv("CHATCHAT_SECRET_FILE", raising=False)
    monkeypatch.setenv("CHATCHAT_HOME", str(tmp_path / "no-home"))
    for key, value in (("API_KEY", "sk-env"), ("BASE_URL", "https://env.example/v1"), ("TYPE", "openai")):
        monkeypatch.setenv(f"CHATCHAT_OPENAI_{key}", value)
    assert load_profile("openai")["api_key"] == "sk-env"
