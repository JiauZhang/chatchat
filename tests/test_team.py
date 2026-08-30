import asyncio
import pytest
from unittest.mock import patch

from chatchat.core.runtime import Runtime
from chatchat.agents.agent import Agent, AgentConfig
from chatchat.agents.team import Team, TeamConfig, create_team
from chatchat.core.event import Event, parse_topic
from chatchat.core.ids import make_id
from chatchat.providers.protocol import ChatCompletionChunk, ChunkChoice, Delta, Message
from chatchat.tools.base import tool, ToolContext


@tool(name='roll_dice', description='roll a die', parameters={'type': 'object', 'properties': {}})
def _roll_dice(ctx: ToolContext = None):
    return '1'


def _rt():
    rt = Runtime()
    rt.start()
    rt.registry.register(_roll_dice)
    return rt


class TestTeamCreation:
    def test_basic_creation(self):
        rt = Runtime()
        team = Team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        assert team.id
        assert team.kind == 'team'

    def test_management_tools_injected(self):
        rt = Runtime()
        team = Team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        assert 'create_agent' in team.tools
        assert 'create_team' in team.tools
        assert 'send_message' in team.tools
        assert 'task_stop' in team.tools

    async def test_handle_message_ping(self):
        rt = _rt()
        team = Team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        ev = Event(topic=f'entity:team:{team.id}:request:ping', source=make_id(), data='')
        _, _, ev.type, ev.subtype = parse_topic(ev.topic)
        result = await team.handle_message(ev)
        assert result == 'pong'
        await rt.shutdown()


class TestTeamLifecycle:
    async def test_start_stop(self):
        rt = _rt()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        assert team.is_running
        await team.stop()
        assert not team.is_running
        await rt.shutdown()


class TestIntegration:
    async def test_send_to_team_via_eventbus(self):
        rt = _rt()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        reply = await rt.request(
            source=make_id(), target_id=team.id,
            topic=f'entity:team:{team.id}:request:ping', data='',
            timeout=5,
        )
        assert reply == 'pong'
        await team.stop()
        await rt.shutdown()

    async def test_team_status(self):
        rt = _rt()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        reply = await rt.request(
            source=make_id(), target_id=team.id,
            topic=f'entity:team:{team.id}:request:status', data='',
            timeout=5,
        )
        assert reply['id'] == team.config.id
        assert reply['running'] is True
        await team.stop()
        await rt.shutdown()

    async def test_team_chat_mocked(self):
        rt = _rt()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
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
                topic=f'entity:team:{team.id}:text', data='hello',
                timeout=10,
            )
            assert reply == 'done'
        await team.stop()
        await rt.shutdown()

    async def test_signal_stop(self):
        rt = _rt()
        team = create_team(TeamConfig(provider='agnes', model='agnes-2.5-flash'), runtime=rt)
        assert team.is_running
        await rt.publish(Event(
            topic=f'entity:team:{team.id}:signal:stop',
            source=make_id(),
        ))
        await asyncio.sleep(0.2)
        assert not team.is_running
        await rt.shutdown()


class TestAutonomousSubAgents:
    async def test_create_agent_tool_gives_sub_agent_send_message_and_agent_tools(self):
        rt = _rt()
        team = create_team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ), runtime=rt)

        from chatchat.agents.builtin_tools import create_agent_tool
        # fire-and-forget: spawns a sub-agent and returns its id; it does NOT
        # block on a synchronous reply nor dispatch a first task message.
        result = await create_agent_tool(
            ctx=ToolContext(agent=team), instruction='roll once',
        )
        sub_id = next(iter(team._sub_agents))
        assert sub_id in result
        sub = team._sub_agents[sub_id]
        assert 'send_message' in sub.tools
        assert 'roll_dice' in sub.tools
        await team.stop()
        await rt.shutdown()

    async def test_create_agent_publishes_task_event_fire_and_forget(self):
        from chatchat.providers.client import create_client
        from chatchat.agents.builtin_tools import create_agent_tool

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

        rt = _rt()
        published = []
        orig = rt.publish
        async def spy(ev: Event):
            published.append(ev)
            return await orig(ev)
        rt.publish = spy

        team = create_team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ), runtime=rt)
        with patch('chatchat.agents.agent.create_client', side_effect=fake_client_factory):
            result = await create_agent_tool(
                ctx=ToolContext(agent=team), instruction='roll the die',
            )
        sub_id = next(iter(team._sub_agents))
        assert sub_id in result
        assert team._sub_agents[sub_id].config.instruction.startswith('roll the die')
        assert not any(e.topic.endswith(':text') for e in published)
        await team.stop()
        await rt.shutdown()

    async def _make_team_with_fake_clients(self, content='rolled 6'):
        from chatchat.providers.client import create_client
        from chatchat.providers.protocol import ChatCompletionChunk, ChunkChoice, Delta, Message

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

        rt = _rt()
        team = create_team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            agent_tools=['roll_dice'],
        ), runtime=rt)
        patcher = patch('chatchat.agents.agent.create_client', side_effect=fake_client_factory)
        patcher.start()
        return rt, team, patcher

    async def test_send_message_to_sub_agent(self):
        from chatchat.agents.builtin_tools import create_agent_tool, send_message_tool
        rt, team, patcher = await self._make_team_with_fake_clients()
        try:
            await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            subs = list(team._sub_agents.values())
            assert len(subs) == 2
            a, b = subs[0].id, subs[1].id
            out = await send_message_tool(
                ctx=ToolContext(agent=team), to=a, message='roll', expect_reply=False,
            )
            assert 'message sent' in out
            assert a in out and b is not None
        finally:
            patcher.stop()
            await team.stop()
            await rt.shutdown()

    async def test_task_stop_removes_sub_agent(self):
        from chatchat.agents.builtin_tools import create_agent_tool, task_stop_tool
        rt, team, patcher = await self._make_team_with_fake_clients()
        try:
            await create_agent_tool(
                ctx=ToolContext(agent=team), instruction='roll',
            )
            sub_id = next(iter(team._sub_agents))
            assert sub_id in team._sub_agents
            res = await task_stop_tool(
                ctx=ToolContext(agent=team), agent_id=sub_id,
            )
            assert 'stopped' in res
            assert sub_id not in team._sub_agents
        finally:
            patcher.stop()
            await team.stop()
            await rt.shutdown()

    async def test_full_tournament_runs_end_to_end(self):
        from chatchat.agents.builtin_tools import create_agent_tool, send_message_tool
        rt, team, patcher = await self._make_team_with_fake_clients()
        try:
            await create_agent_tool(ctx=ToolContext(agent=team), instruction='roll')
            sub_id = next(iter(team._sub_agents))
            assert sub_id in team._sub_agents
            out = await send_message_tool(
                ctx=ToolContext(agent=team), message='roll', to=sub_id, expect_reply=False,
            )
            assert 'message sent' in out
        finally:
            patcher.stop()
            await team.stop()
            await rt.shutdown()