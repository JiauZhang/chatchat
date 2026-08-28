from chatchat.runtime import Scheduler, set_runtime, Event, make_id
from chatchat.agent import Agent, AgentConfig
from chatchat.team import Team, TeamConfig
from chatchat.agent_tools import create_agent_tool, send_message_tool
from chatchat.tool import ToolContext


def _leader(runtime):
    # Build the Team but do NOT start its process loop: these tests assert on
    # the event-publishing / notification behaviour, not on running the LLM.
    return Team(TeamConfig(
        name='lead', provider='agnes', model='agnes-2.5-flash',
        instruction='lead', agent_tools=['send_message'],
    ))


async def test_create_agent_publishes_task_event_no_sync_reply():
    runtime = Scheduler()
    set_runtime(runtime)
    published = []
    orig = runtime.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    runtime.publish = spy

    lead = _leader(runtime)
    result = await create_agent_tool(
        ctx=ToolContext(agent=lead), instruction='do something',
    )
    assert 'spawned' in result
    # a task event was published, NOT a synchronous reply consumed
    assert any(t.startswith('entity:agent:') and t.endswith(':text') for t in (e.topic for e in published))


async def test_send_message_publishes_event_only():
    runtime = Scheduler()
    set_runtime(runtime)
    published = []
    orig = runtime.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    runtime.publish = spy

    lead = _leader(runtime)
    sub = Agent(AgentConfig(name='sub', provider='agnes', model='agnes-2.5-flash'))

    out = await send_message_tool(ctx=ToolContext(agent=lead), message='hi', to='sub')
    assert out == 'message sent to sub'
    # exactly one text event published, no request/reply
    texts = [e for e in published if e.topic.endswith(':text')]
    assert len(texts) == 1
    assert texts[0].data == 'hi'


async def test_parent_receives_notification_from_sub_result():
    runtime = Scheduler()
    set_runtime(runtime)
    lead = _leader(runtime)
    published = []
    orig = runtime.publish
    async def spy(ev: Event):
        published.append(ev)
        return await orig(ev)
    runtime.publish = spy

    sub = Agent(AgentConfig(name='sub', provider='agnes', model='agnes-2.5-flash'))
    sub._parent = lead.id
    # a sub-agent finishing with no reply_to target routes its result back to
    # the parent as a notification event.
    await sub._on_unrouted_result('the answer is 42')
    topics = [e.topic for e in published]
    assert any(t.endswith(':notification') for t in topics)
    notif = next(e for e in published if e.topic.endswith(':notification'))
    assert '42' in (notif.data.get('content') or notif.data.get('error') or '')
