from chatchat.client import BaseClient, dynamic_import_client
from chatchat.providers import register_provider, __providers__


def test_register_provider():
    @register_provider('custom')
    class CustomClient(BaseClient):
        base_url = 'https://example.com'

    assert 'custom' in __providers__
    assert dynamic_import_client('custom') is CustomClient