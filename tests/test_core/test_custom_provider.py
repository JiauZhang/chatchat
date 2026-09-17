from chatchat.client import BaseClient, dynamic_import_client
from chatchat.providers import register_provider


@register_provider('custom')
class CustomClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'custom', 'https://example.com', model=model,
            instruction=instruction, http_options=http_options,
        )


def test_custom_provider_registration():
    assert dynamic_import_client('custom') is CustomClient


def test_custom_provider_priority_and_error_list():
    try:
        dynamic_import_client('does-not-exist')
        assert False, 'expected RuntimeError'
    except RuntimeError as e:
        assert 'custom' in str(e)
