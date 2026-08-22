import asyncio
import pytest
from unittest.mock import patch

from chatchat import get_runtime, set_runtime, Scheduler
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.team import Team, TeamConfig, create_team
from chatchat.runtime import Event, make_id
from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message


class TestIntegration:
    async def test_agent_ping_pong(self):
        rt = Scheduler()
        set_runtime(rt)
        agent = create_agent(AgentConfig(name='test', provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}))
        reply = await rt.request(source=make_id(), target_id=agent.id, topic=f'entity:agent:{agent.id}:request:ping', data='', timeout=5)
        assert reply == 'pong'
        await agent.stop()

    async def test_agent_status(self):
        rt = Scheduler()
        set_runtime(rt)
        agent = create_agent(AgentConfig(name='test', provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}))
        reply = await rt.request(source=make_id(), target_id=agent.id, topic=f'entity:agent:{agent.id}:request:status', data='', timeout=5)
        assert reply['name'] == 'test'
        assert reply['running'] is True
        await agent.stop()

    async def test_agent_signal_stop(self):
        rt = Scheduler()
        set_runtime(rt)
        agent = create_agent(AgentConfig(name='test', provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}))
        await rt.publish(Event(topic=f'entity:agent:{agent.id}:signal:stop', source=make_id()))
        await asyncio.sleep(0.2)
        assert not agent.is_running

    async def test_team_status(self):
        rt = Scheduler()
        set_runtime(rt)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        reply = await rt.request(source=make_id(), target_id=team.id, topic=f'entity:team:{team.id}:request:status', data='', timeout=5)
        assert reply['name'] == 'lead'
        await team.stop()

    async def test_team_chat_mocked(self):
        rt = Scheduler()
        set_runtime(rt)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        chunk = ChatCompletionChunk(
            choices=[ChunkChoice(delta=Delta(content='done'), finish_reason='stop')],
        )

        async def fake_chat(*a, **k):
            msg = Message()
            if chunk.choices:
                msg.accumulate(chunk.choices[0].delta)
            team.client.latest = msg
            yield chunk

        with patch.object(team.client, 'chat', side_effect=fake_chat):
            reply = await rt.request(
                source=make_id(), target_id=team.id,
                topic=f'entity:team:{team.id}:text', data='hello', timeout=10,
            )
            assert reply == 'done'
        await team.stop()

    async def test_observer_subscription(self):
        rt = Scheduler()
        set_runtime(rt)
        events = []

        def handler(ev):
            events.append(ev)

        rt.subscribe('lifecycle:*', handler)
        agent = create_agent(AgentConfig(name='test', provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}))
        await agent._emit('start', {'message': 'hello'})
        assert len(events) > 0
        assert events[0].topic == 'lifecycle:agent:start'
        await agent.stop()

    async def test_eventbus_request_unknown_target(self):
        eb = Scheduler()
        with pytest.raises(ValueError, match='Unknown target'):
            await eb.request(source=make_id(), target_id='nobody', topic='entity:agent:nobody:text', data='hi', timeout=0.01)

    async def test_eventbus_publish_fire_and_forget(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('bob', 'agent', q)
        await eb.publish(Event(topic='entity:agent:bob:text', source=make_id(), data='hello'))
        ev = await asyncio.wait_for(q.get(), timeout=1)
        assert ev.data == 'hello'

    async def test_eventbus_subscribe_wildcard(self):
        eb = Scheduler()
        events = []

        def handler(ev):
            events.append(ev)

        eb.subscribe('*', handler)
        await eb.publish(Event(topic='lifecycle:test:event', source='test', data={'key': 'val'}))
        assert len(events) == 1
        assert events[0].topic == 'lifecycle:test:event'
