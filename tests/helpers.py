from chatchat.client import MockClient
from chatchat.team import Team


def mock_team(name, handler=None, usage=None, **kw):
    return Team(name, client_factory=lambda inst, model=None: MockClient(
        handler=handler, usage=usage, model=model), **kw)
