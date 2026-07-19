import json
import tempfile
from chatchat.agent import Agent
from chatchat.tool import Tool, Tools
from chatchat.types import ProgressType


class TestAgentCreation:
    def test_basic_creation(self):
        agent = Agent(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        assert agent.name == 'test'
        assert agent.provider == 'deepseek'
        assert agent.model == 'deepseek-chat'
        assert agent.max_depth == 3
        assert agent.depth == 0
        assert agent.subagents == {}
        assert agent.stream is True
        assert agent.instruction is None

    def test_with_instruction(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        )
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        t = Tool(name='ping', description='ping', tool=lambda: 'pong')
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        )
        assert agent.tools is not None
        assert 'ping' in agent.tools

    def test_max_depth_default(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        assert agent.max_depth == 3


class TestAgentTools:
    def test_get_tools_includes_delegate_tools(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, can_delegate=True,
        )
        tools = agent._get_tools()
        assert 'create_subagent' in tools
        assert 'assign_task' in tools
        assert tools['create_subagent'].name == 'create_subagent'
        assert tools['assign_task'].name == 'assign_task'

    def test_get_tools_with_user_tools(self):
        t = Tool(name='search', description='search', tool=lambda q: q)
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10}, can_delegate=True,
        )
        tools = agent._get_tools()
        assert 'create_subagent' in tools
        assert 'assign_task' in tools
        assert 'search' in tools


class TestAgentClear:
    def test_clear_empties_subagents(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        agent.subagents['child'] = Agent(
            name='child', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        agent.clear()
        assert agent.subagents == {}

    def test_clear_empties_client_messages(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        assert agent.client.messages == []


class TestAgentFindSkill:
    def test_find_skill_no_skills(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        skill = agent._find_skill('anything')
        assert skill is None

    def test_find_skill_llm_failure_graceful(self):
        """When LLM call fails, _find_skill returns None gracefully."""
        import os
        examples_dir = os.path.join(os.path.dirname(__file__), '..', 'examples')
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            skills=[examples_dir], http_options={'timeout': 10},
        )
        # LLM call will fail (no real API key), returns None
        skill = agent._find_skill('weather info')
        # Should not crash, just return None
        assert skill is None


class TestAgentStateDict:
    def test_state_dict_roundtrip(self):
        agent = Agent(
            name='test', provider='deepseek', model='deepseek-chat',
            instruction='test', http_options={'timeout': 10},
        )
        agent.client.messages = [
            {'role': 'system', 'content': 'test'},
            {'role': 'user', 'content': 'hello'},
        ]

        state = agent.state_dict()
        assert state['name'] == 'test'
        assert state['instruction'] == 'test'
        assert state['config']['provider'] == 'deepseek'
        assert state['config']['model'] == 'deepseek-chat'
        assert len(state['messages']) == 2
        assert state['subagents'] == {}

    def test_from_state_dict(self):
        agent = Agent(
            name='original', provider='deepseek', model='deepseek-chat',
            instruction='original', http_options={'timeout': 10},
        )
        agent.client.messages = [
            {'role': 'system', 'content': 'original'},
            {'role': 'user', 'content': 'test'},
        ]

        state = agent.state_dict()
        restored = Agent.from_state_dict(state)
        assert restored.name == 'original'
        assert restored.instruction == 'original'
        assert restored.provider == 'deepseek'
        assert restored.model == 'deepseek-chat'
        assert len(restored.client.messages) == 2


class TestAgentCreateSubagent:
    def test_create_subagent(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, can_delegate=True,
        )
        result = agent._handle_create_subagent(
            name='child',
            description='You are a helpful test assistant.',
        )
        assert 'child' in agent.subagents
        assert agent.subagents['child'].name == 'child'
        assert agent.subagents['child'].instruction == 'You are a helpful test assistant.'
        assert 'created' in result

    def test_create_subagent_already_exists(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, can_delegate=True,
        )
        agent._handle_create_subagent(name='child', description='helper')
        result = agent._handle_create_subagent(name='child', description='another')
        assert 'already exists' in result
        assert agent.subagents['child'].instruction == 'helper'

    def test_create_subagent_uses_description_when_no_skill_matches(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, can_delegate=True,
        )
        result = agent._handle_create_subagent(
            name='child',
            description='You are a custom assistant with no matching skill.',
        )
        assert 'created' in result
        assert agent.subagents['child'].instruction == 'You are a custom assistant with no matching skill.'


class TestAgentAssignTask:
    def test_assign_task_not_found(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, can_delegate=True,
        )
        result = agent._handle_assign_task(name='child', message='task')
        assert 'Error' in result
        assert 'not found' in result

    def test_assign_task_depth_limit(self):
        agent = Agent(
            name='root', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=1, can_delegate=True,
        )
        agent.depth = 1
        agent._handle_create_subagent(name='child', description='helper')
        result = agent._handle_assign_task(name='child', message='task')
        assert 'Error' in result
        assert 'maximum delegation depth' in result


class TestAgentExecuteToolCalls:
    def test_execute_tool_calls_returns_result(self):
        t = Tool(name='echo', description='echo', tool=lambda x: x)
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        )

        from chatchat.types import ToolCall
        tc = ToolCall(id='call_1', name='echo', arguments='{"x": "hello"}')
        results = agent._execute_tool_calls([tc])

        assert len(results) == 1
        assert results[0]['role'] == 'tool'
        assert results[0]['content'] == 'hello'
        assert results[0]['tool_call_id'] == 'call_1'