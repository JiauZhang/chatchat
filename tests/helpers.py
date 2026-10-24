from chatchat.client import MockClient
from chatchat.team.product import TeamProduct
from chatchat.team.team import Team


def mock_team(name, handler=None, usage=None, **kw):
    return Team(name, client_factory=lambda inst, model=None: MockClient(handler=handler, usage=usage, model=model), **kw)


class RecordingProduct(TeamProduct):
    """A product that only remembers what the runtime told it."""

    def __init__(self):
        self.cwds = []
        self.modes = []
        self.granted = []

    def cwd_changed(self, cwd):
        self.cwds.append(cwd)

    def plan_mode_changed(self, mode):
        self.modes.append(mode)

    def skills_granted(self, tools):
        self.granted.append(tuple(tools))
