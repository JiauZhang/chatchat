import asyncio

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
        ctx=ToolContext(agent=lead), to=sub.id, message='hi',
    )
    assert sub.id in out
    # exactly one text event published; sender is carried by the event source
    texts = [e for e in published if e.topic.endswith(':text')]
    assert len(texts) == 1
    assert texts[0].source == lead.id
    assert texts[0].data == 'hi'
    await rt.shutdown()


async def test_send_message_is_fire_and_forget():
    rt = Runtime()
    lead = _leader(rt)
    sub = Agent(AgentConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)

    out = await send_message_tool(
        ctx=ToolContext(agent=lead), to=sub.id, message='ping',
    )
    assert 'message sent' in out
    # 纯 fire-and-forget：无任何回复账本，事件直接落进目标邮箱
    ev = await asyncio.wait_for(sub._mailbox.get(), timeout=1)
    assert ev.data == 'ping'
    assert ev.source == lead.id
    await rt.shutdown()


async def test_peer_reply_carries_sender_envelope():
    rt = Runtime()
    lead = _leader(rt)
    sub = Agent(AgentConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
    published = []
    orig = rt.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    rt.publish = spy

    # 对端用 send_message 回信：发送方 id 由事件 source 携带，收方据此识别“这是谁的话”。
    await send_message_tool(
        ctx=ToolContext(agent=sub), to=lead.id, message='the answer is 42',
    )
    assert any(e.topic.endswith(':text') and e.source == sub.id for e in published)
    await rt.shutdown()