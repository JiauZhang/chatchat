from chatchat.core.event import Event
from chatchat.core.runtime import Runtime
from chatchat.agents.agent import Agent, AgentConfig
from chatchat.agents.team import Team, TeamConfig
from chatchat.agents.builtin_tools import create_agent_tool, send_message_tool
from chatchat.tools.base import ToolContext


def _leader(runtime):
    # Build the Team but do NOT start its process loop: these tests assert on
    # the event-publishing / notification behaviour, not on running the LLM.
    return Team(TeamConfig(
        provider='agnes', model='agnes-2.5-flash',
        instruction='lead', agent_tools=['send_message'],
    ), runtime=runtime)


async def test_create_agent_returns_id_and_dispatches_nothing():
    rt = Runtime()
    published = []
    orig = rt.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    rt.publish = spy

    lead = _leader(rt)
    result = await create_agent_tool(
        ctx=ToolContext(agent=lead), instruction='do something',
    )
    # the tool reports the new sub-agent id and it is registered under that id
    sub_id = next(iter(lead._sub_agents))
    assert sub_id in result
    assert sub_id in lead._sub_agents
    # creating a sub-agent must NOT dispatch a first text task message; it
    # stays idle until the caller sends a task via send_message.
    assert not any(e.topic.endswith(':text') for e in published)
    await rt.shutdown()


async def test_send_message_publishes_event_only():
    rt = Runtime()
    published = []
    orig = rt.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    rt.publish = spy

    lead = _leader(rt)
    sub = Agent(AgentConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)

    out = await send_message_tool(
        ctx=ToolContext(agent=lead), to=sub.id, message='hi', expect_reply=False,
    )
    assert sub.id in out
    # exactly one text event published, no request/reply
    texts = [e for e in published if e.topic.endswith(':text')]
    assert len(texts) == 1
    assert texts[0].data == 'hi'
    await rt.shutdown()


async def test_send_message_expect_reply_tracks_ledger():
    rt = Runtime()
    lead = _leader(rt)
    sub = Agent(AgentConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)

    out = await send_message_tool(
        ctx=ToolContext(agent=lead), to=sub.id, message='ping', expect_reply=True,
    )
    assert 'message sent' in out
    assert sub.id in lead._pending_reply
    assert lead.has_open_replies
    await rt.shutdown()


async def test_sender_receives_notification_from_source():
    rt = Runtime()
    lead = _leader(rt)
    sub = Agent(AgentConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
    published = []
    orig = rt.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    rt.publish = spy

    # a sub-agent finishing a message routes its result back to the message's
    # source (whoever asked), as a notification.
    await sub._send_notification(lead.id, 'the answer is 42')
    topics = [e.topic for e in published]
    assert any(t.endswith(':notification') for t in topics)
    notif = next(e for e in published if e.topic.endswith(':notification'))
    assert '42' in (notif.data.get('content') or notif.data.get('error') or '')
    await rt.shutdown()