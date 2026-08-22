import asyncio
from unittest.mock import patch

from chatchat import get_runtime, set_runtime, Scheduler
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.team import Team, TeamConfig, create_team
from chatchat.runtime import Event, make_id, parse_topic
from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message


class TestTeamCreation:
    def test_basic_creation(self):
        team = Team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        assert team.name == 'lead'
        assert team.kind == 'team'

    def test_management_tools_injected(self):
        team = Team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        assert 'create_agent' in team.tools
        assert 'create_team' in team.tools
        assert 'send_message' in team.tools
        assert 'task_stop' in team.tools


class TestTeamLifecycle:
    async def test_start_stop(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        assert team.is_running
        await team.stop()
        assert not team.is_running


class TestHandleMessage:
    async def test_text_routes_to_chat(self):
        team = Team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        ev = Event(topic='entity:team:lead:request:ping', source=make_id(), data='')
        _, _, ev.type, ev.subtype = parse_topic(ev.topic)
        result = await team.handle_message(ev)
        assert result == 'pong'


class TestIntegration:
    async def test_send_to_team_via_eventbus(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        reply = await runtime.request(
            source=make_id(), target_id=team.id,
            topic=f'entity:team:{team.id}:request:ping', data='',
            timeout=5,
        )
        assert reply == 'pong'
        await team.stop()

    async def test_team_status(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        reply = await runtime.request(
            source=make_id(), target_id=team.id,
            topic=f'entity:team:{team.id}:request:status', data='',
            timeout=5,
        )
        assert reply['name'] == 'lead'
        assert reply['running'] is True
        await team.stop()

    async def test_team_chat_mocked(self):
        runtime = Scheduler()
        set_runtime(runtime)
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
            reply = await runtime.request(
                source=make_id(), target_id=team.id,
                topic=f'entity:team:{team.id}:text', data='hello',
                timeout=10,
            )
            assert reply == 'done'
        await team.stop()

    async def test_signal_stop(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='agnes', model='agnes-2.5-flash'))
        assert team.is_running
        await runtime.publish(Event(
            topic=f'entity:team:{team.id}:signal:stop',
            source=make_id(),
        ))
        await asyncio.sleep(0.2)
        assert not team.is_running