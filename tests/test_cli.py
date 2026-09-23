import asyncio
import json
import subprocess
import sys
from argparse import Namespace

from chatchat.cli.team import LEAD, _run
from chatchat.client import load_secret
from chatchat.cli import config as config_cli


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
    args = Namespace(params=['deepseek', 'chat'], thinking='off',
                     thinking_budget=0, effort='',
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
    team = _demo(monkeypatch, thinking='adaptive', thinking_budget=8000,
                 effort='high', no_hooks=True)[0]
    setting = team.kw['thinking']
    assert (setting.mode, setting.budget, setting.effort) == (
        'adaptive', 8000, 'high')
    assert team.kw['hooks'] is False
    assert team.kw['http_options'] == {'proxy': None, 'timeout': None}


def test_the_team_command_is_reachable_from_the_cli():
    done = subprocess.run([sys.executable, '-m', 'chatchat', 'team', '--help'],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert 'usage: __main__.py team' in done.stdout


def _home(monkeypatch, tmp_path, setting, value):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv(setting, value)
    monkeypatch.delenv('CHATCHAT_AGNES_API_KEY', raising=False)
    monkeypatch.delenv('CHATCHAT_DEEPSEEK_API_KEY', raising=False)
    return tmp_path


def _config(monkeypatch, tmp_path, cfgs, setting='CHATCHAT_SECRET_FILE',
            value='state/secrets.json'):
    home = _home(monkeypatch, tmp_path, setting,
                 value if value.startswith('~/') else str(tmp_path / value))
    config_cli.parse_config(Namespace(list=False, cfgs=cfgs))
    return home / value.removeprefix('~/')


def test_config_creates_the_secret_file_and_the_directory_above_it(monkeypatch,
                                                                   tmp_path):
    """On a fresh machine there is no secret file to open, so the writer has
    to create it instead of letting open() fail."""
    target = _config(monkeypatch, tmp_path, 'agnes.api_key=sk-new')
    assert json.loads(target.read_text()) == {'agnes': {'api_key': 'sk-new'}}


def test_a_tilde_in_the_secret_file_setting_reaches_the_home_directory(monkeypatch,
                                                                       tmp_path):
    target = _config(monkeypatch, tmp_path, 'agnes.api_key=sk-new',
                     value='~/chatchat.json')
    assert (tmp_path / 'chatchat.json').exists()
    assert target == tmp_path / 'chatchat.json'
    assert not (tmp_path / '~').exists()


def test_config_keeps_every_entry_already_in_the_secret_file(monkeypatch,
                                                             tmp_path):
    target = _config(monkeypatch, tmp_path, 'agnes.api_key=sk-old')
    target.write_text(json.dumps({'agnes': {'api_key': 'sk-old', 'extra': 1},
                                  'deepseek': {'api_key': 'keep'}}))
    _config(monkeypatch, tmp_path, 'agnes.api_key=sk-new')
    assert json.loads(target.read_text()) == {
        'agnes': {'api_key': 'sk-new', 'extra': 1},
        'deepseek': {'api_key': 'keep'}}


def test_config_refuses_to_overwrite_a_secret_file_it_cannot_read(monkeypatch,
                                                                  tmp_path):
    target = _config(monkeypatch, tmp_path, 'agnes.api_key=sk-new')
    target.write_text('{not json')
    _config(monkeypatch, tmp_path, 'agnes.api_key=sk-other')
    assert target.read_text() == '{not json'


def test_config_refuses_a_provider_that_is_not_registered(monkeypatch,
                                                          tmp_path, capsys):
    target = _config(monkeypatch, tmp_path, 'nope.api_key=x')
    assert 'nope' in capsys.readouterr().out
    assert not target.exists()


def test_config_lists_the_builtin_names_without_importing_them(monkeypatch,
                                                               tmp_path,
                                                               capsys):
    _home(monkeypatch, tmp_path, 'CHATCHAT_SECRET_FILE', 'state/secrets.json')
    config_cli.parse_config(Namespace(list=True, cfgs=None))
    printed = capsys.readouterr().out
    assert 'agnes' in printed and 'openrouter' in printed


def test_a_tilde_in_chatchat_home_is_expanded_while_reading_secrets(monkeypatch,
                                                                    tmp_path):
    (tmp_path / '.pyclaw').mkdir()
    (tmp_path / '.pyclaw' / 'chatchat.json').write_text(
        json.dumps({'agnes': {'api_key': 'from-home'}}))
    _home(monkeypatch, tmp_path, 'CHATCHAT_HOME', '~/.pyclaw')
    monkeypatch.delenv('CHATCHAT_SECRET_FILE', raising=False)
    assert load_secret('agnes') == {'api_key': 'from-home'}
