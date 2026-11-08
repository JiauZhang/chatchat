from chatchat.runtime.config import ModelConfig, RuntimeConfig
from chatchat.runtime.product import TeamProduct
from chatchat.runtime.runtime import Runtime
from chatchat.team.team import Team
from chatchat.testing import MockClient


def _config(handler, usage, kw):
    model_kw = {}
    if "model" in kw:
        model_kw["name"] = kw.pop("model")
    for key in ("thinking", "client", "client_factory", "http_options", "protocols"):
        if key in kw:
            model_kw[key] = kw.pop(key)
    if "client_factory" not in model_kw and "client" not in model_kw:
        model_kw["client_factory"] = lambda inst, model=None: MockClient(handler=handler, usage=usage, model=model)
    return RuntimeConfig(model=ModelConfig(**model_kw), **kw)


def mock_team(name, handler=None, usage=None, *, mailbox_dir=None, team_store=None, **kw):
    return Team(name, _config(handler, usage, kw), mailbox_dir=mailbox_dir, team_store=team_store)


def mock_runtime(name, handler=None, usage=None, **kw):
    return Runtime(name, _config(handler, usage, kw))


class RecordingProduct(TeamProduct):
    """A product that only remembers what the runtime told it."""

    def __init__(self):
        self.cwds = []
        self.granted = []

    def cwd_changed(self, cwd):
        self.cwds.append(cwd)

    def skills_granted(self, tools):
        self.granted.append(tuple(tools))
