from __future__ import annotations

from chatchat.client import Client
from chatchat.runtime.thinking import Thinking
from chatchat.team.standing import with_standing


class ModelChoice:
    """Which model the team talks to, and how a client for it is made.

    A host may bring its own client, or a factory that makes one per
    instruction, and may switch the model or the thinking level later. The
    choice holds that, and nothing else: the team asks it for a client and
    hands the lead's back to it when the model changes.
    """

    def __init__(self, *, factory=None, client=None, model=None, thinking=None, client_kw=None):
        self.factory = factory
        self.client = client
        self.model = model
        self.thinking = thinking or Thinking()
        self.client_kw = dict(client_kw or {})

    def client_for(
        self,
        instruction: str,
        thinking: Thinking | None = None,
        model: str | None = None,
        standing: bool = True,
    ) -> Client:
        if standing:
            instruction = with_standing(instruction)
        if self.factory is not None:
            return self.factory(instruction, model)
        if self.client is not None:
            return self.client
        return Client(
            model=model or self.model,
            instruction=instruction,
            thinking=self.thinking if thinking is None else thinking,
            **self.client_kw,
        )

    def set_model(self, model: str) -> None:
        self.model = model

    def set_thinking(self, thinking: Thinking) -> None:
        self.thinking = thinking

    @property
    def provider(self) -> str:
        return str(self.model or "").partition("/")[0]
