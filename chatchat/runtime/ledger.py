from __future__ import annotations

from chatchat.runtime.metrics import Metrics
from chatchat.runtime.tokens import measured


def token_count(messages: list[dict]) -> int:
    """The occupancy the provider last reported for this conversation."""
    for message in reversed(messages):
        usage = message.get("usage")
        if isinstance(usage, dict):
            return measured(usage)
    return 0


class Ledger:
    """What a team has spent, summed over the agents that spent it.

    The numbers live on the agents - usage and metrics are per conversation,
    not per team - so the ledger is a view: it is given the lead and a way to
    list the members, and it answers the questions a person asks ("what has
    this cost", "how full is the context") without the team holding them.
    """

    def __init__(self, *, lead, members):
        self.lead = lead
        self.members = members

    def usage(self):
        total = type(self.lead.total_usage)()
        for agent in self.members():
            total.add(agent.total_usage)
        return total

    def last_usage(self):
        for message in reversed(self.lead.messages):
            usage = message.get("usage")
            if isinstance(usage, dict):
                return type(self.lead.total_usage).from_dict(usage)
        return None

    def restore(self, usage: dict, metrics: dict) -> None:
        """Carry the numbers of a conversation that is being continued into the
        agent that will keep it, so the counts a person reads go on growing
        instead of starting over. Both per-turn fields are set: the first turn
        after a resume must report its own work, not the whole history."""
        lead = self.lead
        lead.total_usage = type(lead.total_usage).from_dict(usage)
        known = Metrics().as_dict()
        seeded = Metrics(**{name: int(metrics.get(name) or 0) for name in known})
        lead.metrics = seeded
        lead.last_metrics = seeded
        lead.total_metrics = seeded

    def reset(self) -> None:
        for agent in self.members():
            agent.total_usage = type(self.lead.total_usage)()
            agent.metrics = Metrics()
            agent.last_metrics = Metrics()
            agent.total_metrics = Metrics()

    def turn_metrics(self) -> Metrics:
        return self.lead.last_metrics

    def total_metrics(self) -> Metrics:
        total = Metrics()
        for agent in self.members():
            total = total + agent.total_metrics
        return total

    def context_tokens(self) -> int:
        return token_count(self.lead.messages)
