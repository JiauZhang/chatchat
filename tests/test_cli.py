import asyncio
import subprocess
import sys
from argparse import Namespace

from chatchat.cli.team import LEAD, _run


class _Recorder:

    built = []

    def __init__(self, name, **kw):
        self.kw = kw
        self.prompt = None
        kw.setdefault('members', [])
        _Recorder.built.append(self)

    def add(self, name, instruction):
        self.kw['members'].append((name, instruction))

    async def query(self, prompt):
        self.prompt = prompt
        return 'the answer'


def _demo(monkeypatch, **overrides):
    _Recorder.built = []
    monkeypatch.setattr('chatchat.cli.team.Team', _Recorder)
    args = Namespace(params=['deepseek', 'chat'], thinking=False,
                     no_hooks=False, proxy=None, timeout=None, prompt='go')
    for key, value in overrides.items():
        setattr(args, key, value)
    asyncio.run(_run(args))
    return _Recorder.built


def test_the_demo_builds_a_lead_with_two_teammates(monkeypatch):
    team = _demo(monkeypatch)[0]
    assert team.kw['provider'] == 'deepseek'
    assert team.kw['model'] == 'chat'
    assert team.kw['lead_instruction'] == LEAD
    assert [name for name, _ in team.kw['members']] == ['researcher', 'writer']
    assert team.prompt == 'go'


def test_the_demo_flags_reach_the_team(monkeypatch):
    team = _demo(monkeypatch, thinking=True, no_hooks=True)[0]
    assert team.kw['thinking'] is True
    assert team.kw['hooks'] is False
    assert team.kw['http_options'] == {'proxy': None, 'timeout': None}


def test_the_team_command_is_reachable_from_the_cli():
    done = subprocess.run([sys.executable, '-m', 'chatchat', 'team', '--help'],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert 'usage: __main__.py team' in done.stdout
