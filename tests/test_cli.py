import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from argparse import Namespace

from chatchat.cli.team import LEAD, _run
from chatchat.client import load_profile, rate_limits, secret_file
from chatchat.cli import config as config_cli


class _Recorder:
    built = []

    def __init__(self, name, **kw):
        self.kw = kw
        self.prompt = None
        kw.setdefault("members", [])
        _Recorder.built.append(self)

    def add(self, name, instruction):
        self.kw["members"].append((name, instruction))

    async def query(self, prompt):
        self.prompt = prompt
        return "the answer"


def _demo(monkeypatch, **overrides):
    _Recorder.built = []
    monkeypatch.setattr("chatchat.cli.team.Team", _Recorder)
    args = Namespace(
        params=["deepseek/chat"],
        thinking="off",
        effort="",
        no_hooks=False,
        proxy=None,
        timeout=None,
        prompt="go",
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    asyncio.run(_run(args))
    return _Recorder.built


def test_the_demo_builds_a_lead_with_two_teammates(monkeypatch):
    team = _demo(monkeypatch)[0]
    assert team.kw["model"] == "deepseek/chat"
    assert team.kw["lead_instruction"] == LEAD
    assert [name for name, _ in team.kw["members"]] == ["researcher", "writer"]
    assert team.prompt == "go"


def test_the_demo_flags_reach_the_team(monkeypatch):
    team = _demo(monkeypatch, thinking="max", no_hooks=True)[0]
    setting = team.kw["thinking"]
    assert setting.level == "max"
    assert team.kw["hooks"] is False
    assert team.kw["http_options"] == {"proxy": None, "timeout": None}


def test_the_team_command_is_reachable_from_the_cli():
    done = subprocess.run([sys.executable, "-m", "chatchat", "team", "--help"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "usage: __main__.py team" in done.stdout


def _home(monkeypatch, tmp_path, setting, value):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(setting, value)
    monkeypatch.delenv("CHATCHAT_AGNES_API_KEY", raising=False)
    monkeypatch.delenv("CHATCHAT_DEEPSEEK_API_KEY", raising=False)
    return tmp_path


def _config(monkeypatch, tmp_path, argv, setting="CHATCHAT_SECRET_FILE", value="state/secrets.json"):
    home = _home(monkeypatch, tmp_path, setting, value if value.startswith("~/") else str(tmp_path / value))
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    config_cli.cli_config(subparsers)
    args = parser.parse_args(["config"] + argv)
    code = args.parser(args)
    return home / value.removeprefix("~/"), code


def test_config_creates_the_secret_file_and_the_directory_above_it(monkeypatch, tmp_path):
    """On a fresh machine there is no secret file to open, so the writer has
    to create it instead of letting open() fail."""
    target, code = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-new"])
    assert code == 0
    assert json.loads(target.read_text()) == {"agnes": {"api_key": "sk-new"}}
    assert target.stat().st_mode & 0o777 == 0o600


def test_a_tilde_in_the_secret_file_setting_reaches_the_home_directory(monkeypatch, tmp_path):
    target, _ = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-new"], value="~/chatchat.json")
    assert (tmp_path / "chatchat.json").exists()
    assert target == tmp_path / "chatchat.json"
    assert not (tmp_path / "~").exists()


def test_config_keeps_every_entry_already_in_the_secret_file(monkeypatch, tmp_path):
    target, _ = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-old"])
    target.write_text(json.dumps({"agnes": {"api_key": "sk-old", "extra": 1}, "deepseek": {"api_key": "keep"}}))
    _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-new"])
    assert json.loads(target.read_text()) == {"agnes": {"api_key": "sk-new", "extra": 1}, "deepseek": {"api_key": "keep"}}


def test_config_writes_only_the_fields_it_was_given(monkeypatch, tmp_path):
    target, _ = _config(
        monkeypatch,
        tmp_path,
        ["--provider", "agnes", "--api-key", "sk-1", "--base-url", "https://x.example/v1", "--type", "openai"],
    )
    _config(monkeypatch, tmp_path, ["--provider", "agnes", "--rpm", "60"])
    assert json.loads(target.read_text()) == {
        "agnes": {"api_key": "sk-1", "base_url": "https://x.example/v1", "type": "openai", "rpm": 60}
    }


def test_config_refuses_to_overwrite_a_secret_file_it_cannot_read(monkeypatch, tmp_path):
    target, _ = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-new"])
    target.write_text("{not json")
    _, code = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--api-key", "sk-other"])
    assert code == 1
    assert target.read_text() == "{not json"


def test_config_accepts_any_profile_name(monkeypatch, tmp_path):
    """Profiles are user data now: there is no registry to refuse a name."""
    target, _ = _config(monkeypatch, tmp_path, ["--provider", "nope", "--api-key", "x"])
    assert json.loads(target.read_text()) == {"nope": {"api_key": "x"}}


def test_config_requires_a_provider_when_writing(monkeypatch, tmp_path, capsys):
    _, code = _config(monkeypatch, tmp_path, ["--api-key", "x"])
    assert code == 1
    assert "--provider" in capsys.readouterr().out


def test_config_rejects_a_non_positive_rpm(monkeypatch, tmp_path, capsys):
    _, code = _config(monkeypatch, tmp_path, ["--provider", "agnes", "--rpm", "0"])
    assert code == 1
    assert "positive" in capsys.readouterr().out


def test_config_shows_profiles_with_masked_keys(monkeypatch, tmp_path, capsys):
    target = tmp_path / "state" / "secrets.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"agnes": {"type": "openai", "base_url": "https://x.example/v1", "api_key": "sk-1234567890abcd", "rpm": 60}})
    )
    _, code = _config(monkeypatch, tmp_path, [])
    printed = capsys.readouterr().out
    assert code == 0
    assert "agnes" in printed and "config file" in printed
    assert "sk-123****abcd" in printed
    assert "sk-1234567890abcd" not in printed
    assert "rpm=60" in printed


def test_config_show_with_no_profiles_says_so(monkeypatch, tmp_path, capsys):
    _config(monkeypatch, tmp_path, [])
    assert "(no profiles configured)" in capsys.readouterr().out


class TestRateLimits:
    def _write(self, monkeypatch, tmp_path, data):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data))
        monkeypatch.setenv("CHATCHAT_SECRET_FILE", str(path))
        return path

    def test_reads_rpm_next_to_each_profile(self, monkeypatch, tmp_path):
        self._write(monkeypatch, tmp_path, {"agnes": {"rpm": 60}, "deepseek": {"rpm": "120"}, "kimi": {}})
        assert rate_limits() == {"agnes": 60, "deepseek": 120}

    def test_ignores_non_numeric_and_missing_limits(self, monkeypatch, tmp_path):
        self._write(monkeypatch, tmp_path, {"agnes": {"rpm": "lots"}, "kimi": {"rpm": None}, "other": "not-a-profile"})
        assert rate_limits() == {}

    def test_missing_or_broken_files_yield_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHATCHAT_SECRET_FILE", str(tmp_path / "absent.json"))
        assert rate_limits() == {}
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")
        monkeypatch.setenv("CHATCHAT_SECRET_FILE", str(broken))
        assert rate_limits() == {}


def test_the_secret_file_defaults_to_chatchat_config(monkeypatch):
    monkeypatch.delenv("CHATCHAT_SECRET_FILE", raising=False)
    assert str(secret_file()) == str(Path("~/.chatchat/config.json").expanduser())


def test_profiles_live_in_their_own_file_not_chatchat_home(monkeypatch, tmp_path):
    """CHATCHAT_HOME no longer decides where credentials live."""
    (tmp_path / ".pyclaw").mkdir()
    (tmp_path / ".pyclaw" / "chatchat.json").write_text(
        json.dumps({"agnes": {"type": "openai", "base_url": "https://apihub.agnes-ai.com/v1", "api_key": "from-home"}})
    )
    _home(monkeypatch, tmp_path, "CHATCHAT_HOME", "~/.pyclaw")
    monkeypatch.delenv("CHATCHAT_SECRET_FILE", raising=False)
    try:
        load_profile("agnes")
        assert False, "chatchat.json under CHATCHAT_HOME must be ignored"
    except RuntimeError as e:
        assert "base_url" in str(e) or "agnes" in str(e)
