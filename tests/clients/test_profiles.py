import json

import pytest

from chatchat.client import load_profile


def _secret_file(monkeypatch, tmp_path, data):
    path = tmp_path / 'chatchat.json'
    path.write_text(json.dumps(data))
    monkeypatch.setenv('CHATCHAT_SECRET_FILE', str(path))
    return path


def test_official_openai_needs_only_an_api_key(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {'openai': {'api_key': 'sk-x'}})
    profile = load_profile('openai')
    assert profile == {'type': 'openai',
                       'base_url': 'https://api.openai.com/v1',
                       'api_key': 'sk-x'}


def test_official_anthropic_carries_its_own_wire_type(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {'anthropic': {'api_key': 'sk-a'}})
    profile = load_profile('anthropic')
    assert profile['type'] == 'anthropic'
    assert profile['base_url'] == 'https://api.anthropic.com'


def test_official_name_can_still_declare_a_proxy_base_url(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'anthropic': {'api_key': 'sk-a',
                                'base_url': 'https://relay.local'}})
    assert load_profile('anthropic')['base_url'] == 'https://relay.local'


def test_a_custom_profile_defaults_to_the_openai_wire(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'agnes': {'api_key': 'sk-1',
                            'base_url': 'https://apihub.agnes-ai.com/v1'}})
    profile = load_profile('agnes')
    assert profile['type'] == 'openai'
    assert profile['base_url'] == 'https://apihub.agnes-ai.com/v1'


def test_a_custom_profile_can_declare_the_anthropic_wire(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'kimi': {'type': 'anthropic', 'api_key': 'sk-k',
                           'base_url': 'https://api.moonshot.ai'}})
    assert load_profile('kimi')['type'] == 'anthropic'


def test_a_custom_profile_without_base_url_is_refused(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path, {'agnes': {'api_key': 'sk-1'}})
    with pytest.raises(RuntimeError) as e:
        load_profile('agnes')
    assert 'base_url' in str(e.value)


def test_a_profile_without_api_key_is_refused(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'agnes': {'base_url': 'https://apihub.agnes-ai.com/v1'}})
    with pytest.raises(RuntimeError) as e:
        load_profile('agnes')
    assert 'api_key' in str(e.value)


def test_an_unknown_wire_type_is_refused(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'agnes': {'type': 'grpc', 'api_key': 'k',
                            'base_url': 'https://x.example'}})
    with pytest.raises(RuntimeError) as e:
        load_profile('agnes')
    assert 'grpc' in str(e.value)


def test_env_overrides_beat_the_profile_entry(monkeypatch, tmp_path):
    _secret_file(monkeypatch, tmp_path,
                 {'agnes': {'api_key': 'file-key',
                            'base_url': 'https://file.example/v1'}})
    monkeypatch.setenv('CHATCHAT_AGNES_API_KEY', 'env-key')
    monkeypatch.setenv('CHATCHAT_AGNES_BASE_URL', 'https://env.example/v1')
    monkeypatch.setenv('CHATCHAT_AGNES_TYPE', 'anthropic')
    profile = load_profile('agnes')
    assert profile == {'type': 'anthropic',
                       'base_url': 'https://env.example/v1',
                       'api_key': 'env-key'}


def test_env_api_key_alone_serves_an_official_name(monkeypatch, tmp_path):
    monkeypatch.delenv('CHATCHAT_SECRET_FILE', raising=False)
    monkeypatch.setenv('CHATCHAT_HOME', str(tmp_path / 'no-home'))
    monkeypatch.setenv('CHATCHAT_OPENAI_API_KEY', 'sk-env')
    assert load_profile('openai')['api_key'] == 'sk-env'
