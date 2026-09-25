import pytest

from chatchat.client import BaseClient, dynamic_import_client
from chatchat.providers import __providers__, provider_names, register_provider


@register_provider('custom')
class CustomClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'custom', 'https://example.com', model=model,
            instruction=instruction, http_options=http_options,
        )


def test_custom_provider_registration():
    assert dynamic_import_client('custom') is CustomClient


def test_custom_provider_error_lists_the_known_names():
    with pytest.raises(RuntimeError) as excinfo:
        dynamic_import_client('does-not-exist')
    assert 'custom' in str(excinfo.value)


def test_builtin_providers_register_in_the_same_mapping():
    """A builtin is a provider like any other: it reaches the registry through
    register_provider, so no lookup path is reserved for it."""
    agnes = dynamic_import_client('agnes')
    assert __providers__['agnes'] is agnes
    assert agnes.__name__ == 'AgnesClient'


def test_the_provider_list_is_complete_before_any_module_is_imported():
    names = provider_names()
    for builtin in ('agnes', 'alibaba', 'baidu', 'deepseek', 'google',
                    'openrouter', 'tencent', 'xunfei', 'zhipu'):
        assert builtin in names
    assert 'custom' in names


def test_only_a_registered_module_can_be_a_provider():
    for name in ('client', 'os.path', 'nope'):
        assert name not in provider_names()
    with pytest.raises(RuntimeError):
        dynamic_import_client('os.path')


def test_registering_a_name_again_replaces_its_client():
    @register_provider('dup')
    class First(BaseClient):
        pass

    @register_provider('dup')
    class Second(BaseClient):
        pass

    assert dynamic_import_client('dup') is Second
