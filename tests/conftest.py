import pytest


@pytest.fixture(autouse=True)
def _isolated_runtime_sinks():
    from chatchat.hooks import events
    events.clear_runtime_sinks()
    yield
    events.clear_runtime_sinks()
