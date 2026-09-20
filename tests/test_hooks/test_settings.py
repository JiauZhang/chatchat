import json

from chatchat.hooks.schemas import HookCommand, IndividualHookConfig
from chatchat.hooks.settings import (dedupe_hooks, get_all_hooks, is_hook_equal,
                                     hook_from_dict, settings_file_paths)


def _write(cwd, source, data):
    path = settings_file_paths(cwd)[source]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_hook_from_dict():
    hook = hook_from_dict({'type': 'command', 'command': 'echo hi',
                           'if': 'Bash(git *)', 'statusMessage': 'msg',
                           'async': True, 'timeout': 5})
    assert hook is not None
    assert hook.type == 'command'
    assert hook.if_ == 'Bash(git *)'
    assert hook.status_message == 'msg'
    assert hook.async_ is True
    assert hook.timeout == 5
    assert hook_from_dict({'type': 'function'}) is None
    assert hook_from_dict({'type': 'nope'}) is None


def test_layered_loading(tmp_path, monkeypatch):
    monkeypatch.setattr('chatchat.hooks.settings.Path.home',
                        lambda: tmp_path / 'home')
    cwd = tmp_path / 'proj'
    cwd.mkdir()
    _write(tmp_path / 'home', 'userSettings', {'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': 'user-hook'}]}]}})
    _write(cwd, 'projectSettings', {'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': 'project-hook'}]}]}})
    _write(cwd, 'localSettings', {'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': 'local-hook'}]}]}})
    hooks = get_all_hooks(cwd)
    commands = [h.config.command for h in hooks]
    assert commands == ['user-hook', 'project-hook', 'local-hook']


def test_same_file_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr('chatchat.hooks.settings.Path.home',
                        lambda: tmp_path)
    cwd = tmp_path / 'proj'
    cwd.mkdir()
    _write(tmp_path, 'userSettings', {'hooks': {'Stop': [{'hooks': [
        {'type': 'command', 'command': 'x'}]}]}})
    hooks = get_all_hooks(cwd)
    assert len(hooks) == 1


def test_dedupe_first_wins():
    h1 = HookCommand(type='command', command='same')
    h2 = HookCommand(type='command', command='same')
    h3 = HookCommand(type='command', command='same', timeout=99)
    from chatchat.hooks.schemas import IndividualHookConfig
    hooks = [IndividualHookConfig(event='Stop', config=h1, source='a', hook_id='1'),
             IndividualHookConfig(event='Stop', config=h2, source='b', hook_id='2'),
             IndividualHookConfig(event='Stop', config=h3, source='c', hook_id='3')]
    deduped = dedupe_hooks(hooks)
    assert [h.hook_id for h in deduped] == ['1']


def test_is_hook_equal_ignores_timeout():
    a = HookCommand(type='command', command='c', shell='bash')
    b = HookCommand(type='command', command='c', shell='bash', timeout=30)
    c = HookCommand(type='command', command='c', shell='bash', if_='Bash(x)')
    assert is_hook_equal(a, b)
    assert not is_hook_equal(a, c)
    assert not is_hook_equal(a, HookCommand(type='prompt', prompt='c'))


def test_malformed_settings_skipped(tmp_path):
    _write(tmp_path, 'projectSettings', {'hooks': {'Stop': [
        {'hooks': [{'type': 'bogus'}]}, {'matcher': 'X'}]}})
    hooks = get_all_hooks(tmp_path)
    assert hooks == []
