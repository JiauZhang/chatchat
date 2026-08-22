import asyncio
import pytest
from unittest.mock import patch

from chatchat import get_runtime, set_runtime, Scheduler
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.agent_tools import send_message_tool, task_stop_tool
from chatchat.client import BaseClient
from chatchat.exceptions import SubAgentError
from chatchat.runtime import Event, make_id
from chatchat.team import Team, TeamConfig, create_team
from chatchat.tool import Tool, ToolContext
from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta, Message


class TestAgentCreation:
    def test_basic_creation(self):
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        assert agent.name == 'test'
        assert agent.provider == 'agnes'
        assert agent.model == 'agnes-2.5-flash'

    def test_with_instruction(self):
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        ))
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        t = Tool(name='ping', description='ping', func=lambda: 'pong')
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            tools=[t], http_options={'timeout': 10},
        ))
        assert agent.tools is not None
        assert 'ping' in agent.tools


class TestAgentClear:
    def test_clear_empties_client_messages(self):
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        assert agent.client.messages == []


class TestAgentStateDict:
    def test_from_state_dict(self):
        agent = Agent(AgentConfig(
            name='original', provider='agnes', model='agnes-2.5-flash',
            instruction='original', http_options={'timeout': 10},
        ))
        agent.client.messages = [
            {'role': 'system', 'content': 'original'},
            {'role': 'user', 'content': 'test'},
        ]

        state = agent.state_dict()
        restored = Agent.from_state_dict(state)
        assert restored.name == 'original'
        assert restored.instruction == 'original'
        assert restored.provider == 'agnes'
        assert restored.model == 'agnes-2.5-flash'
        assert len(restored.client.messages) == 2


class TestAgentLifecycle:
    async def test_start_stop(self):
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        assert not agent.is_running
        agent.start()
        assert agent.is_running
        await agent.stop()
        assert not agent.is_running

    async def test_ping_pong(self):
        runtime = Scheduler()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        reply = await runtime.request(
            source=make_id(), target_id=agent.id,
            topic=f'entity:agent:{agent.id}:request:ping', data='',
            timeout=5,
        )
        assert reply == 'pong'
        await agent.stop()

    async def test_status_request(self):
        runtime = Scheduler()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        reply = await runtime.request(
            source=make_id(), target_id=agent.id,
            topic=f'entity:agent:{agent.id}:request:status', data='',
            timeout=5,
        )
        assert reply['name'] == 'test'
        assert reply['running'] is True
        await agent.stop()

    async def test_signal_stop(self):
        runtime = Scheduler()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        await runtime.publish(Event(
            topic=f'entity:agent:{agent.id}:signal:stop',
            source=make_id(),
        ))
        await asyncio.sleep(0.2)
        assert not agent.is_running


class TestSubAgent:
    async def test_create_sub_agent(self):
        team = Team(TeamConfig(
            name='parent', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        sub = team.create_sub_agent(AgentConfig(
            name='child', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        assert sub.name == 'child'
        assert sub.is_running
        assert 'child' in team._sub_agents
        await sub.stop()
        await team.stop()

    async def test_create_sub_agent_with_config(self):
        team = Team(TeamConfig(
            name='parent', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        sub = team.create_sub_agent(AgentConfig(
            name='researcher', provider='agnes', model='agnes-2.5-flash',
            instruction='You are a research assistant.',
            http_options={'timeout': 10},
        ))
        assert sub.name == 'researcher'
        assert sub.is_running
        await sub.stop()
        await team.stop()


class TestManagementTools:
    def test_management_tools_register_on_agent(self):
        agent = Agent(AgentConfig(
            name='test', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        agent.add_tool(send_message_tool)
        agent.add_tool(task_stop_tool)
        assert 'send_message' in agent.tools
        assert 'task_stop' in agent.tools

    async def test_send_message_unknown_target(self):
        agent = Agent(AgentConfig(
            name='alice', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        agent.add_tool(send_message_tool)
        tool = agent.tools['send_message']
        result = await tool(ctx=ToolContext(agent=agent), to='nobody', message='hi')
        assert 'unknown agent' in result

    async def test_send_message_known_target(self):
        runtime = Scheduler()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='alice', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        target = Agent(AgentConfig(
            name='bob', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        agent.add_tool(send_message_tool)
        agent.start()
        target.start()
        tool = agent.tools['send_message']
        result = await tool(ctx=ToolContext(agent=agent), to='bob', message='hello')
        assert 'message sent' in result
        await agent.stop()
        await target.stop()

    async def test_task_stop_unknown_sub_agent(self):
        agent = Agent(AgentConfig(
            name='alice', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        agent.add_tool(task_stop_tool)
        tool = agent.tools['task_stop']
        result = await tool(ctx=ToolContext(agent=agent), name='nobody')
        assert 'unknown sub-agent' in result


class TestSkillsInjection:
    def test_skills_instruction_injected_into_client(self, tmp_path):
        skill_dir = tmp_path / 'myskill'
        skill_dir.mkdir()
        (skill_dir / 'SKILL.md').write_text(
            '---\nname: testskill\ndescription: a test skill\n---\nUsage here.\n',
            encoding='utf-8',
        )
        agent = Agent(AgentConfig(
            name='sk', provider='agnes', model='agnes-2.5-flash',
            instruction='base instruction', skills=[str(skill_dir)],
            http_options={'timeout': 10},
        ))
        assert 'testskill' in agent.instruction
        assert 'testskill' in agent.client.config.instruction

    def test_no_skills_keeps_instruction(self):
        agent = Agent(AgentConfig(
            name='sk', provider='agnes', model='agnes-2.5-flash',
            instruction='base instruction', http_options={'timeout': 10},
        ))
        assert agent.instruction == 'base instruction'
        assert agent.client.config.instruction == 'base instruction'


class TestDelegation:
    async def test_create_agent_tool_delegates_via_scheduler(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(
            name='parent', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))
        chunk = ChatCompletionChunk(
            choices=[ChunkChoice(delta=Delta(content='done'), finish_reason='stop')],
        )

        async def fake_chat(*args, **kwargs):
            msg = Message()
            if chunk.choices:
                msg.accumulate(chunk.choices[0].delta)
            for sub in team._sub_agents.values():
                sub.client.latest = msg
            yield chunk

        with patch.object(BaseClient, 'chat', side_effect=fake_chat):
            result = await asyncio.wait_for(
                team.tools['create_agent'](ctx=ToolContext(agent=team), instruction='hello'), timeout=5,
            )
        assert '[Agent' in result
        assert 'completed' in result
        assert 'done' in result
        await team.stop()

    async def test_create_agent_tool_reports_sub_error(self):
        runtime = Scheduler()
        set_runtime(runtime)
        team = create_team(TeamConfig(
            name='parent', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))

        def raise_chat(*args, **kwargs):
            async def gen():
                raise RuntimeError('boom')
                yield
            return gen()

        with patch.object(BaseClient, 'chat', side_effect=raise_chat):
            with pytest.raises(SubAgentError):
                await asyncio.wait_for(
                    team.tools['create_agent'](ctx=ToolContext(agent=team), instruction='hello'), timeout=5,
                )
        await team.stop()

    async def test_create_sub_team_max_depth(self):
        team = Team(TeamConfig(
            name='t', provider='agnes', model='agnes-2.5-flash',
            max_depth=0, http_options={'timeout': 10},
        ))
        with pytest.raises(Exception):
            team.create_sub_team(TeamConfig(
                name='sub', provider='agnes', model='agnes-2.5-flash',
                http_options={'timeout': 10},
            ))
        await team.stop()


class TestAgentChat:
    async def test_chat_returns_reply(self):
        agent = create_agent(AgentConfig(
            name='c', provider='agnes', model='agnes-2.5-flash',
            http_options={'timeout': 10},
        ))

        async def fake_chat(*a, **k):
            agent.client.latest = Message(content='hi there')
            yield ChatCompletionChunk(
                choices=[ChunkChoice(delta=Delta(content='hi there'))],
            )

        with patch.object(agent.client, 'chat', side_effect=fake_chat):
            result = await agent.chat('hello')
        assert result == 'hi there'
        await agent.stop()
