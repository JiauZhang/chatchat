from chatchat.scheduler import Scheduler
from chatchat.agent import Agent, AgentConfig
from chatchat.tool import Tool


class TestAgentCreation:
    def test_basic_creation(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        assert agent.name == 'test'
        assert agent.provider == 'deepseek'
        assert agent.model == 'deepseek-chat'
        assert agent.stream is True

    def test_with_instruction(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        ), s)
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        s = Scheduler()
        t = Tool(name='ping', description='ping', tool=lambda: 'pong')
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        ), s)
        assert agent.tools is not None
        assert 'ping' in agent.tools

    def test_tool_emit_fn_set(self):
        s = Scheduler()
        t = Tool(name='t', description='t', tool=lambda: 'ok')
        Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        ), s)
        assert t._emit_fn is not None


class TestAgentClear:
    def test_clear_empties_client_messages(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        assert agent.client.messages == []


class TestAgentStateDict:
    def test_from_state_dict(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='original', provider='deepseek', model='deepseek-chat',
            instruction='original', http_options={'timeout': 10},
        ), s)
        agent.client.messages = [
            {'role': 'system', 'content': 'original'},
            {'role': 'user', 'content': 'test'},
        ]

        state = agent.state_dict()
        restored = Agent.from_state_dict(state, scheduler=s)
        assert restored.name == 'original'
        assert restored.instruction == 'original'
        assert restored.provider == 'deepseek'
        assert restored.model == 'deepseek-chat'
        assert len(restored.client.messages) == 2


class TestAgentLifecycle:
    def test_start_stop(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        assert not agent.is_running
        agent.start()
        assert agent.is_running
        agent.stop()
        assert not agent.is_running

    def test_ping_pong(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        s.register(agent)
        agent.start()
        from chatchat.message import Message, ID
        msg = Message(sender=ID(), recipient=agent.id, type='request', subtype='ping')
        reply = s.request(msg, timeout=5)
        assert reply.payload == 'pong'
        agent.stop()

    def test_status_request(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        s.register(agent)
        agent.start()
        from chatchat.message import Message, ID
        msg = Message(sender=ID(), recipient=agent.id, type='request', subtype='status')
        reply = s.request(msg, timeout=5)
        assert reply.payload['name'] == 'test'
        assert reply.payload['running'] is True
        agent.stop()

    def test_signal_stop(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        s.register(agent)
        agent.start()
        from chatchat.message import Message, ID
        msg = Message(sender=ID(), recipient=agent.id, type='signal', subtype='stop')
        s.send(msg)
        import time
        time.sleep(0.2)
        assert not agent.is_running


class TestSubAgent:
    def test_create_sub_agent(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        sub = agent.create_sub_agent(AgentConfig(
            name='child', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ))
        assert sub.name == 'child'
        assert sub.is_running
        assert 'child' in agent._sub_agents
        sub.stop()

    def test_create_sub_agent_with_config(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='parent', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
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
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, management_tools=True,
        ), s)
        assert 'create_agent' in agent.tools
        assert 'send_message' in agent.tools
        assert 'task_stop' in agent.tools

    def test_send_message_unknown_target(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, management_tools=True,
        ), s)
        tool = agent.tools['send_message']
        result = tool(to='nobody', message='hi')
        assert 'unknown agent' in result

    def test_send_message_known_target(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, management_tools=True,
        ), s)
        s.register(agent)
        target = Agent(AgentConfig(
            name='bob', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        s.register(target)
        agent.start()
        target.start()
        tool = agent.tools['send_message']
        result = tool(to='bob', message='hello')
        assert 'message sent' in result
        agent.stop()
        target.stop()

    def test_task_stop_unknown_sub_agent(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, management_tools=True,
        ), s)
        tool = agent.tools['task_stop']
        result = tool(name='nobody')
        assert 'unknown sub-agent' in result

    def test_create_agent_detects_duplicate(self):
        s = Scheduler()
        agent = Agent(AgentConfig(
            name='alice', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10}, management_tools=True,
        ), s)
        # Pre-populate a sub-agent to test duplicate detection (no real API call)
        sub = Agent(AgentConfig(
            name='dup', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        ), s)
        agent._sub_agents['dup'] = sub
        tool = agent.tools['create_agent']
        result = tool(name='dup', instruction='test')
        assert 'already exists' in result