import pytest
from chatchat.hooks import events


@pytest.fixture(autouse=True)
def _isolated_runtime_sinks():

    events.clear_runtime_sinks()
    yield
    events.clear_runtime_sinks()
