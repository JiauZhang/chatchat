import asyncio

from chatchat.client import MockClient
from chatchat.team.team import Team


def _team():
    """A team, built where it can be built: inside a running loop.

    The client is made per instruction, the way a host that switches model
    or thinking level gets a new one.
    """
    return Team("demo", client_factory=lambda instruction, model=None: MockClient(name=instruction))


def test_the_client_that_asks_the_model_is_the_one_the_answer_is_read_from():
    """Changing the thinking level gives the lead a new client. The caller
    that asks the model has to be given it too, or it keeps asking through
    the old one while the answer is read from the new one - and the old one
    is the one that has been used, so the numbers would come from nowhere."""

    async def main():
        team = _team()
        lead = team.lead
        before = lead.client
        team.set_thinking(lead.client.thinking)
        return lead.client is not before, lead.caller.client is lead.client

    changed, agrees = asyncio.run(main())
    assert changed
    assert agrees


def test_the_usage_that_is_recorded_is_the_usage_of_the_call_that_made_it():
    """The numbers on a message are the ones the call that produced it
    reported."""

    async def main():
        team = _team()
        await team.conversation.query("hello")
        return team.lead.messages[-1]

    message = asyncio.run(main())
    assert message["usage"] is not None
    assert "prompt_tokens" in message["usage"]


def test_switching_the_model_gives_the_caller_the_new_client():
    """Switching the model is the same thing as switching the thinking
    level: the lead gets a new client, and the caller has to be given it."""

    async def main():
        team = _team()
        lead = team.lead
        before = lead.client
        team.set_model("agnes/agnes-3.0-flash")
        return lead.client is not before, lead.caller.client is lead.client

    changed, agrees = asyncio.run(main())
    assert changed
    assert agrees
