from chatchat.client import MockClient
from chatchat.runtime.product import TeamProduct
from chatchat.team.team import Team


def mock_team(name, handler=None, usage=None, **kw):
    return Team(name, client_factory=lambda inst, model=None: MockClient(handler=handler, usage=usage, model=model), **kw)


class RecordingProduct(TeamProduct):
    """A product that only remembers what the runtime told it."""

    def __init__(self):
        self.cwds = []
        self.granted = []

    def cwd_changed(self, cwd):
        self.cwds.append(cwd)

    def skills_granted(self, tools):
        self.granted.append(tuple(tools))
