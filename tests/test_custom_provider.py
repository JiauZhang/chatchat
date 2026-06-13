from chatchat.client import BaseClient, dynamic_import_client
from chatchat.providers import register_provider, __custom_providers__


def test_register_provider():
    @register_provider('custom')
    class CustomClient(BaseClient):
        pass

    assert 'custom' in __custom_providers__
    assert dynamic_import_client('custom') is CustomClient