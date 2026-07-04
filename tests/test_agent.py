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
        assert agent._depth == 0
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
    def test_get_tools_includes_delegate(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        tools = agent._get_tools()
        assert 'delegate' in tools
        assert tools['delegate'].name == 'delegate'

    def test_get_tools_with_user_tools(self):
        t = Tool(name='search', description='search', tool=lambda q: q)
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        )
        tools = agent._get_tools()
        assert 'delegate' in tools
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
    def test_find_skill_by_name(self):
        """Test with a real skill directory."""
        import os
        examples_dir = os.path.join(os.path.dirname(__file__), '..', 'examples')
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            skills=[examples_dir], http_options={'timeout': 10},
        )
        skill = agent._find_skill('weather')
        assert skill is not None
        assert skill.name == 'weather'

    def test_find_skill_not_found(self):
        agent = Agent(
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        skill = agent._find_skill('nonexistent')
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


class TestAgentDelegate:
    def test_delegate_creates_subagent(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=3,
        )
        from chatchat import APIError
        try:
            agent._handle_delegate(
                name='child',
                message='test task',
                instruction='You are a test assistant.',
            )
        except APIError:
            pass
        # Subagent should be created even if the API call fails
        assert 'child' in agent.subagents
        assert agent.subagents['child'].name == 'child'
        assert agent.subagents['child'].instruction == 'You are a test assistant.'

    def test_delegate_reuses_subagent(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=3,
        )
        from chatchat import APIError
        # Manually create the subagent to avoid API call
        child = Agent(
            name='child', provider='deepseek', model='deepseek-chat',
            instruction='helper', http_options={'timeout': 10},
        )
        child.client.messages = [{'role': 'user', 'content': 'existing'}]
        agent.subagents['child'] = child
        agent._bridge_events(child)

        original_msgs = list(child.client.messages)
        try:
            agent._handle_delegate(name='child', message='second', instruction='helper')
        except APIError:
            pass
        assert agent.subagents['child'].client.messages == original_msgs

    def test_delegate_reuses_subagent_ignores_different_instruction(self):
        """When reusing a subagent, a different instruction is ignored."""
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=3,
        )
        from chatchat import APIError
        child = Agent(
            name='child', provider='deepseek', model='deepseek-chat',
            instruction='helper', http_options={'timeout': 10},
        )
        agent.subagents['child'] = child
        agent._bridge_events(child)

        # Instruction is not updated on reuse — the original stays
        assert child.instruction == 'helper'
        # The delegate call proceeds (will fail with APIError since no real API key)
        try:
            agent._handle_delegate(name='child', message='second', instruction='different')
        except APIError:
            pass
        # The original instruction remains unchanged
        assert child.instruction == 'helper'

    def test_delegate_depth_limit(self):
        agent = Agent(
            name='root', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=1,
        )
        agent._depth = 1
        result = agent._handle_delegate(name='child', message='task')
        assert 'Error' in result
        assert 'maximum delegation depth' in result

    def test_delegate_with_skill_not_found(self):
        agent = Agent(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, max_depth=3,
        )
        result = agent._handle_delegate(
            name='child', message='task', skill='nonexistent',
        )
        assert 'Error' in result
        assert 'skill' in result.lower()


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