from __future__ import annotations

from chatchat.client import Client
from chatchat.runtime.config import ModelConfig
from chatchat.runtime.thinking import Thinking
from chatchat.runtime.standing import with_standing


class ModelChoice:
    """Which model the team talks to, and how a client for it is made.

    A host may bring its own client, or a factory that makes one per
    instruction, and may switch the model or the thinking level later. The
    choice holds that, and nothing else: the team asks it for a client and
    hands the lead's back to it when the model changes.
    """

    def __init__(self, *, client_factory=None, client=None, model=None, thinking=None, client_options=None):
        self.client_factory = client_factory
        self.client = client
        self.model = model
        self.thinking = thinking or Thinking()
        self.client_options = dict(client_options or {})

    @classmethod
    def from_config(cls, config: ModelConfig) -> "ModelChoice":
        options = {"http_options": dict(config.http_options)}
        if config.protocols is not None:
            options["protocols"] = config.protocols
        return cls(
            client_factory=config.client_factory,
            client=config.client,
            model=config.name,
            thinking=config.thinking,
            client_options=options,
        )

    def client_for(
        self,
        instruction: str,
        thinking: Thinking | None = None,
        model: str | None = None,
        standing: bool = True,
    ) -> Client:
        if standing:
            instruction = with_standing(instruction)
        if self.client_factory is not None:
            return self.client_factory(instruction, model)
        if self.client is not None:
            return self.client
        return Client(
            model=model or self.model,
            instruction=instruction,
            thinking=self.thinking if thinking is None else thinking,
            **self.client_options,
        )

    def set_model(self, model: str) -> None:
        self.model = model

    def set_thinking(self, thinking: Thinking) -> None:
        self.thinking = thinking

    @property
    def provider(self) -> str:
        return str(self.model or "").partition("/")[0]
