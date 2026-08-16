from chatchat import get_runtime, set_runtime, Runtime
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.message import Message, make_id
from chatchat.tool import Tool


class TestAgentCreation:
    def test_basic_creation(self):
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        assert agent.name == 'test'
        assert agent.provider == 'deepseek'
        assert agent.model == 'deepseek-chat'

    def test_with_instruction(self):
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        ))
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        t = Tool(name='ping', description='ping', tool=lambda: 'pong')
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        ))
        assert agent.tools is not None
        assert 'ping' in agent.tools


class TestAgentClear:
    def test_clear_empties_client_messages(self):
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        assert agent.client.messages == []


class TestAgentStateDict:
    def test_from_state_dict(self):
        agent = Agent(AgentConfig(
            name='original', provider='deepseek', model='deepseek-chat',
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
        assert restored.provider == 'deepseek'
        assert restored.model == 'deepseek-chat'
        assert len(restored.client.messages) == 2


class TestAgentLifecycle:
    def test_start_stop(self):
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        assert not agent.is_running
        agent.start()
        assert agent.is_running
        agent.stop()
        assert not agent.is_running

    def test_ping_pong(self):
        runtime = Runtime()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        msg = Message(sender=make_id(), recipient=agent.id, type='request', subtype='ping')
        reply = runtime.request(msg, timeout=5)
        assert reply.payload == 'pong'
        agent.stop()

    def test_status_request(self):
        runtime = Runtime()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        msg = Message(sender=make_id(), recipient=agent.id, type='request', subtype='status')
        reply = runtime.request(msg, timeout=5)
        assert reply.payload['name'] == 'test'
        assert reply.payload['running'] is True
        agent.stop()

    def test_signal_stop(self):
        runtime = Runtime()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        msg = Message(sender=make_id(), recipient=agent.id, type='signal', subtype='stop')
        runtime.send(msg)
        import time
        time.sleep(0.2)
        assert not agent.is_running


class TestSubAgent:
    def test_create_sub_agent(self):
        agent = Agent(AgentConfig(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        sub = agent.create_sub_agent(AgentConfig(
            name='child', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        assert sub.name == 'child'
        assert sub.is_running
        assert 'child' in agent._sub_agents
        sub.stop()

    def test_create_sub_agent_with_config(self):
        agent = Agent(AgentConfig(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        sub = agent.create_sub_agent(AgentConfig(
            name='researcher', provider='deepseek', model='deepseek-chat',
            instruction='You are a research assistant.',
            http_options={'timeout': 10},
        ))
        assert sub.name == 'researcher'
        assert sub.is_running
        sub.stop()


class TestManagementTools:
    def test_create_agent_tool_auto_injected(self):
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        from chatchat.agent_tools import create_agent_tool, send_message_tool, task_stop_tool
        agent.add_tool(create_agent_tool(agent))
        agent.add_tool(send_message_tool(agent))
        agent.add_tool(task_stop_tool(agent))
        assert 'create_agent' in agent.tools
        assert 'send_message' in agent.tools
        assert 'task_stop' in agent.tools

    def test_send_message_unknown_target(self):
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        from chatchat.agent_tools import send_message_tool
        agent.add_tool(send_message_tool(agent))
        tool = agent.tools['send_message']
        result = tool(to='nobody', message='hi')
        assert 'unknown agent' in result

    def test_send_message_known_target(self):
        runtime = Runtime()
        set_runtime(runtime)
        agent = create_agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        target = Agent(AgentConfig(
            name='bob', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        runtime.register(target)
        from chatchat.agent_tools import send_message_tool
        agent.add_tool(send_message_tool(agent))
        agent.start()
        target.start()
        tool = agent.tools['send_message']
        result = tool(to='bob', message='hello')
        assert 'message sent' in result
        agent.stop()
        target.stop()

    def test_task_stop_unknown_sub_agent(self):
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        from chatchat.agent_tools import task_stop_tool
        agent.add_tool(task_stop_tool(agent))
        tool = agent.tools['task_stop']
        result = tool(name='nobody')
        assert 'unknown sub-agent' in result

    def test_create_agent_detects_duplicate(self):
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        from chatchat.agent_tools import create_agent_tool
        agent.add_tool(create_agent_tool(agent))
        from chatchat.message import make_id
        dup_id = make_id()
        sub = Agent(AgentConfig(
            name=dup_id, provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        agent._sub_agents[dup_id] = sub
        tool = agent.tools['create_agent']
        sub2 = Agent(AgentConfig(
            name='other', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        agent._sub_agents['other'] = sub2
        assert dup_id in agent._sub_agents
        assert 'other' in agent._sub_agents