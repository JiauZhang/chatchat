import asyncio
import pytest
from unittest.mock import patch

from chatchat.core.runtime import Runtime
from chatchat.agents.agent import Agent, AgentConfig, create_agent
from chatchat.agents.team import TeamConfig, create_team
from chatchat.core.event import Event
from chatchat.core.ids import make_id
from chatchat.providers.protocol import ChatCompletionChunk, ChunkChoice, Delta, Message


class TestIntegration:
    async def test_agent_ping_pong(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}), runtime=rt)
        reply = await rt.request(source=make_id(), target_id=agent.id, topic=f'entity:agent:{agent.id}:request:ping', data='', timeout=5)
        assert reply == 'pong'
        await agent.stop()
        await rt.shutdown()

    async def test_agent_status(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}), runtime=rt)
        reply = await rt.request(source=make_id(), target_id=agent.id, topic=f'entity:agent:{agent.id}:request:status', data='', timeout=5)
        assert reply['id'] == agent.config.id
        assert reply['running'] is True
        await agent.stop()
        await rt.shutdown()

    async def test_agent_signal_stop(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}), runtime=rt)
        await rt.publish(Event(topic=f'entity:agent:{agent.id}:signal:stop', source=make_id()))
        await asyncio.sleep(0.2)
        assert not agent.is_running
        await rt.shutdown()

    async def test_team_status(self):
        rt = Runtime()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        reply = await rt.request(source=make_id(), target_id=team.id, topic=f'entity:team:{team.id}:request:status', data='', timeout=5)
        assert reply['id'] == team.config.id
        await team.stop()
        await rt.shutdown()

    async def test_team_chat_mocked(self):
        rt = Runtime()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)

        async def fake_chat(*a, **k):
            msg = Message()
            msg.accumulate(Delta(content='done'))
            team.client.latest = msg
            yield ChatCompletionChunk(choices=[ChunkChoice(delta=Delta(content='done'))])

        with patch.object(team.client, 'chat', side_effect=fake_chat):
            reply = await rt.request(
                source=make_id(), target_id=team.id,
                topic=f'entity:team:{team.id}:text', data='hello', timeout=10,
            )
            assert reply == 'done'
        await team.stop()
        await rt.shutdown()

    async def test_observer_subscription(self):
        rt = Runtime()
        events = []

        def handler(ev):
            events.append(ev)

        rt.subscribe('lifecycle:*', handler)
        agent = create_agent(AgentConfig(provider='agnes', model='agnes-2.5-flash', http_options={'timeout': 10}), runtime=rt)
        await agent._emit('start', {'message': 'hello'})
        assert len(events) > 0
        assert events[0].topic == 'lifecycle:agent:start'
        await agent.stop()
        await rt.shutdown()

    async def test_eventbus_request_unknown_target(self):
        eb = Runtime()
        with pytest.raises(ValueError, match='Unknown target'):
            await eb.request(source=make_id(), target_id='nobody', topic='entity:agent:nobody:text', data='hi', timeout=0.01)
        await eb.shutdown()

    async def test_eventbus_publish_fire_and_forget(self):
        eb = Runtime()
        q = asyncio.Queue()
        eb.register_entity('bob', 'agent', q)
        await eb.publish(Event(topic='entity:agent:bob:text', source=make_id(), data='hello'))
        ev = await asyncio.wait_for(q.get(), timeout=1)
        assert ev.data == 'hello'
        await eb.shutdown()

    async def test_eventbus_subscribe_wildcard(self):
        eb = Runtime()
        events = []

        def handler(ev):
            events.append(ev)

        eb.subscribe('*', handler)
        await eb.publish(Event(topic='lifecycle:test:event', source='test', data={'key': 'val'}))
        assert len(events) == 1
        assert events[0].topic == 'lifecycle:test:event'
        await eb.shutdown()