import asyncio
import pytest
from unittest.mock import patch

from chatchat.core.runtime import Runtime
from chatchat.agents.agent import Agent, AgentConfig, create_agent
from chatchat.providers.client import BaseClient
from chatchat.core.exceptions import SubAgentError
from chatchat.core.event import Event
from chatchat.core.ids import make_id
from chatchat.agents.team import Team, TeamConfig, create_team
from chatchat.tools.base import Tool, ToolContext
from chatchat.providers.protocol import ChatCompletionChunk, ChunkChoice, Delta, Message


class TestAgentCreation:
    def test_basic_creation(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        assert agent.id
        assert agent.provider == 'agnes'
        assert agent.model == 'agnes-2.5-flash'

    def test_with_instruction(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        ), runtime=rt)
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        rt = Runtime()
        t = Tool(name='ping', description='ping', func=lambda: 'pong')
        rt.registry.register(t)
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            tools=['ping'], http_options={'timeout': 10},
        ), runtime=rt)
        assert agent.tools is not None
        assert 'ping' in agent.tools


class TestAgentClear:
    def test_clear_empties_client_messages(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        assert agent.client.messages == []


class TestAgentStateDict:
    def test_from_state_dict(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='original', http_options={'timeout': 10},
        ), runtime=rt)
        agent.client.messages = [
            {'role': 'system', 'content': 'original'},
            {'role': 'user', 'content': 'test'},
        ]

        state = agent.state_dict()
        # free the id so the restored agent (which reuses it) can re-register
        rt.unregister_entity(agent.id)
        restored = Agent.from_state_dict(state, runtime=rt)
        assert restored.config.id == agent.config.id
        assert restored.instruction == 'original'
        assert restored.provider == 'agnes'
        assert restored.model == 'agnes-2.5-flash'
        assert len(restored.client.messages) == 2

    def test_from_state_dict_roundtrips_full_config(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='You are a researcher.', description='research bot',
            background=True, max_steps=20, http_options={'timeout': 10},
        ), runtime=rt)
        rt.unregister_entity(agent.id)
        restored = Agent.from_state_dict(agent.state_dict(), runtime=rt)
        assert restored.config.id == agent.config.id
        assert restored.config.background is True
        assert restored.config.description == 'research bot'
        assert restored.config.max_steps == 20


class TestAgentLifecycle:
    async def test_start_stop(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        assert not agent.is_running
        agent.start()
        assert agent.is_running
        await agent.stop()
        assert not agent.is_running
        await rt.shutdown()

    async def test_ping_pong(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        reply = await rt.request(
            source=make_id(), target_id=agent.id,
            topic=f'entity:agent:{agent.id}:request:ping', data='',
            timeout=5,
        )
        assert reply == 'pong'
        await agent.stop()
        await rt.shutdown()

    async def test_status_request(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        reply = await rt.request(
            source=make_id(), target_id=agent.id,
            topic=f'entity:agent:{agent.id}:request:status', data='',
            timeout=5,
        )
        assert reply['id'] == agent.config.id
        assert reply['running'] is True
        await agent.stop()
        await rt.shutdown()

    async def test_signal_stop(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        await rt.publish(Event(
            topic=f'entity:agent:{agent.id}:signal:stop',
            source=make_id(),
        ))
        await asyncio.sleep(0.2)
        assert not agent.is_running
        await rt.shutdown()


class TestSubAgent:
    async def test_create_sub_agent(self):
        rt = Runtime()
        team = Team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        sub = team.create_sub_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        assert sub.is_running
        assert sub.id in team._sub_agents
        await sub.stop()
        await team.stop()
        await rt.shutdown()

    async def test_create_sub_agent_with_config(self):
        rt = Runtime()
        team = Team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        sub = team.create_sub_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='You are a research assistant.',
            http_options={'timeout': 10},
        ))
        assert sub.is_running
        await sub.stop()
        await team.stop()
        await rt.shutdown()


class TestManagementTools:
    def test_tools_from_config(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
            tools=['send_message', 'task_stop'],
        ), runtime=rt)
        assert 'send_message' in agent.tools
        assert 'task_stop' in agent.tools

    async def test_send_message_unknown_target(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
            tools=['send_message'],
        ), runtime=rt)
        tool = agent.tools['send_message']
        result = await tool(ctx=ToolContext(agent=agent), to='nobody',
                            message='hi', expect_reply=False)
        assert 'unknown agent' in result
        await rt.shutdown()

    async def test_send_message_known_target(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
            tools=['send_message'],
        ), runtime=rt)
        target = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        target.start()
        tool = agent.tools['send_message']
        result = await tool(ctx=ToolContext(agent=agent), to=target.id,
                            message='hello', expect_reply=False)
        assert 'message sent' in result
        await agent.stop()
        await target.stop()
        await rt.shutdown()

    async def test_task_stop_unknown_sub_agent(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
            tools=['task_stop'],
        ), runtime=rt)
        tool = agent.tools['task_stop']
        result = await tool(ctx=ToolContext(agent=agent), agent_id='nobody')
        assert 'unknown sub-agent' in result
        await rt.shutdown()


class TestSkillsInjection:
    def test_skills_instruction_injected_into_client(self, tmp_path):
        skill_dir = tmp_path / 'myskill'
        skill_dir.mkdir()
        (skill_dir / 'SKILL.md').write_text(
            '---\nname: testskill\ndescription: a test skill\n---\nUsage here.\n',
            encoding='utf-8',
        )
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='base instruction', skills=[str(skill_dir)],
            http_options={'timeout': 10},
        ), runtime=rt)
        assert 'testskill' in agent.instruction
        assert 'testskill' in agent.client.config.instruction

    def test_no_skills_keeps_instruction(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            instruction='base instruction', http_options={'timeout': 10},
        ), runtime=rt)
        assert agent.instruction == 'base instruction'
        assert agent.client.config.instruction == 'base instruction'


class TestDelegation:
    async def test_create_agent_tool_spawns_sub_agent_fire_and_forget(self):
        rt = Runtime()
        team = create_team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)
        chunk = ChatCompletionChunk(
            choices=[ChunkChoice(delta=Delta(content='done'), finish_reason='stop')],
        )

        async def fake_chat(*args, **kwargs):
            yield chunk

        with patch.object(BaseClient, 'chat', side_effect=fake_chat):
            result = await asyncio.wait_for(
                team.tools['create_agent'](ctx=ToolContext(agent=team), instruction='hello'), timeout=5,
            )
        sub_id = next(iter(team._sub_agents))
        assert sub_id in result
        assert team._sub_agents[sub_id].config.instruction == 'hello'
        await team.stop()
        await rt.shutdown()

    async def test_create_agent_tool_does_not_block_on_sub_error(self):
        rt = Runtime()
        team = create_team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)

        def raise_chat(*args, **kwargs):
            async def gen():
                raise RuntimeError('boom')
                yield
            return gen()

        with patch.object(BaseClient, 'chat', side_effect=raise_chat):
            result = await asyncio.wait_for(
                team.tools['create_agent'](ctx=ToolContext(agent=team), instruction='hello'), timeout=5,
            )
        sub_id = next(iter(team._sub_agents))
        assert sub_id in result
        await team.stop()
        await rt.shutdown()

    async def test_create_sub_team_max_depth(self):
        rt = Runtime()
        team = Team(TeamConfig(
            provider='agnes', model='agnes-2.5-flash',
            max_depth=0, http_options={'timeout': 10},
        ), runtime=rt)
        with pytest.raises(SubAgentError):
            team.create_sub_team(TeamConfig(
                provider='agnes', model='agnes-2.5-flash',
                http_options={'timeout': 10},
            ))
        await team.stop()
        await rt.shutdown()


class TestAgentChat:
    async def test_text_request_returns_reply(self):
        rt = Runtime()
        agent = create_agent(AgentConfig(
            provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ), runtime=rt)

        async def fake_chat(*a, **k):
            agent.client.latest = Message(content='hi there')
            yield ChatCompletionChunk(
                choices=[ChunkChoice(delta=Delta(content='hi there'))],
            )

        with patch.object(agent.client, 'chat', side_effect=fake_chat):
            reply = await rt.request(
                source=make_id(), target_id=agent.id,
                topic=f'entity:agent:{agent.id}:text', data='hello',
                timeout=5,
            )
        assert reply == 'hi there'
        await agent.stop()
        await rt.shutdown()

    async def test_no_client_returns_error(self):
        rt = Runtime()
        agent = Agent(AgentConfig(
            provider=None, model=None,
        ), runtime=rt)
        agent.start()
        reply = await rt.request(
            source=make_id(), target_id=agent.id,
            topic=f'entity:agent:{agent.id}:text', data='hello',
            timeout=5,
        )
        assert 'No LLM client configured' in reply
        await agent.stop()
        await rt.shutdown()