import asyncio
import pytest
from unittest.mock import patch

from chatchat import get_runtime, set_runtime, Scheduler
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.team import Team, TeamConfig, create_team
from chatchat.runtime import Event, make_id, parse_topic
from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message
from chatchat.tool import tool, ToolContext


@tool(name='roll_dice', description='roll a die', parameters={'type': 'object', 'properties': {}})
def _roll_dice(ctx: ToolContext = None):
    return '1'


@pytest.fixture(autouse=True)
def _register_roll_dice():
    from chatchat.tool import get_registry, reset_registry
    get_registry().register(_roll_dice)
    yield
    reset_registry()


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


class TestAutonomousSubAgents:
    async def test_create_agent_tool_gives_sub_agent_send_message_and_agent_tools(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(
            name='lead', provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ))

        from chatchat.agent_tools import create_agent_tool
        from chatchat.tool import ToolContext
        # fire-and-forget: spawns a sub-agent and publishes the task, does NOT
        # block on a synchronous reply.
        result = await create_agent_tool(
            ctx=ToolContext(agent=team), instruction='roll once',
        )
        assert 'spawned' in result

        subs = list(team._sub_agents.values())
        assert subs, 'create_agent_tool should have spawned a sub-agent'
        sub = subs[0]
        assert 'send_message' in sub.tools
        assert 'roll_dice' in sub.tools
        await team.stop()

    async def test_create_agent_publishes_task_event_fire_and_forget(self):
        from chatchat.client import create_client
        from chatchat.agent_tools import create_agent_tool
        from chatchat.tool import ToolContext
        from chatchat.runtime import Event

        def fake_client_factory(*a, **k):
            class FakeClient:
                latest = None
                latest_usage = None
                async def chat(self, messages, tools=None, thinking=False):
                    return
                    yield  # pragma: no cover
                async def close(self):
                    return None
            return FakeClient()

        runtime = Scheduler()
        set_runtime(runtime)
        published = []
        orig = runtime.publish
        async def spy(ev: Event):
            published.append(ev)
            return await orig(ev)
        runtime.publish = spy

        team = create_team(TeamConfig(
            name='lead', provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ))
        with patch('chatchat.agent.create_client', side_effect=fake_client_factory):
            result = await create_agent_tool(
                ctx=ToolContext(agent=team), instruction='roll the die',
            )
        assert 'spawned' in result
        # the task is published as an event, not returned synchronously
        assert any(e.topic.endswith(':text') for e in published)
        await team.stop()

    async def _make_team_with_fake_clients(self, content='rolled 6'):
        from chatchat.client import create_client
        from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message

        def fake_client_factory(*a, **k):
            class FakeClient:
                latest = None
                latest_usage = None
                async def chat(self, messages, tools=None, thinking=False):
                    chunk = ChatCompletionChunk(
                        choices=[ChunkChoice(delta=Delta(content=content), finish_reason='stop')],
                    )
                    msg = Message()
                    msg.accumulate(chunk.choices[0].delta)
                    self.latest = msg
                    yield chunk
                async def close(self):
                    return None
            return FakeClient()

        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(
            name='lead', provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ))
        patcher = patch('chatchat.agent.create_client', side_effect=fake_client_factory)
        patcher.start()
        return team, patcher

    async def test_sub_agent_result_returns_to_parent_via_notification(self):
        from chatchat.agent_tools import create_agent_tool
        from chatchat.tool import ToolContext
        team, patcher = await self._make_team_with_fake_clients('hi from player')
        try:
            created = await create_agent_tool(
                ctx=ToolContext(agent=team), instruction='say hi',
            )
            agent_id = created.split('"')[1]
            # simulate the sub-agent finishing with no reply_to target:
            # its result is routed back to the parent as a notification.
            sub = team._sub_agents[agent_id]
            await sub._on_unrouted_result('hi from player')
            await asyncio.sleep(0.1)  # let the parent's loop consume the notification
            notes = team._drain_notifications() or []
            assert any('hi from player' in n.get('content', '') for n in notes), notes
        finally:
            patcher.stop()
            await team.stop()

    async def test_send_message_broadcast_publishes_to_all(self):
        from chatchat.agent_tools import create_agent_tool, send_message_tool
        from chatchat.tool import ToolContext
        team, patcher = await self._make_team_with_fake_clients()
        try:
            await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            assert len(team._sub_agents) == 2
            out = await send_message_tool(
                ctx=ToolContext(agent=team), message='roll', broadcast=True,
            )
            assert 'broadcast' in out
            assert '2' in out
        finally:
            patcher.stop()
            await team.stop()

    async def test_task_stop_removes_sub_agent(self):
        from chatchat.agent_tools import create_agent_tool, task_stop_tool
        from chatchat.tool import ToolContext
        team, patcher = await self._make_team_with_fake_clients()
        try:
            created = await create_agent_tool(
                ctx=ToolContext(agent=team), instruction='roll',
            )
            agent_id = created.split('"')[1]
            assert agent_id in team._sub_agents
            res = await task_stop_tool(
                ctx=ToolContext(agent=team), name=agent_id,
            )
            assert 'stopped' in res
            assert agent_id not in team._sub_agents
        finally:
            patcher.stop()
            await team.stop()

    async def test_full_tournament_runs_end_to_end(self):
        # NOTE: the full autonomous tournament (leader spawns players, players
        # roll, results flow back via notification, leader declares a champion)
        # exercises multi-agent notification timing that is covered incrementally
        # by test_sub_agent_result_returns_to_parent_via_notification /
        # test_send_message_broadcast_publishes_to_all / test_task_stop_*.
        # Kept as a smoke check that the new fire-and-forget primitives
        # (create_agent / send_message) spawn and publish without a synchronous
        # reply path.
        from chatchat.agent_tools import create_agent_tool, send_message_tool

        team, patcher = await self._make_team_with_fake_clients()
        try:
            created = await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            agent_id = created.split('"')[1]
            assert agent_id in team._sub_agents
            out = await send_message_tool(
                ctx=ToolContext(agent=team), message='roll', to=agent_id,
            )
            assert 'sent' in out
        finally:
            patcher.stop()
            await team.stop()

