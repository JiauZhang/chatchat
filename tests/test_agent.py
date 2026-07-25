from chatchat.agent import Agent
from chatchat.tool import Tool
from chatchat.event import EventBus


class TestAgentCreation:
    def test_basic_creation(self):
        bus = EventBus(); bus.start()
        agent = Agent(
            event_bus=bus,
            name='test', provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        bus.stop()
        assert agent.name == 'test'
        assert agent.provider == 'deepseek'
        assert agent.model == 'deepseek-chat'
        assert agent.stream is True
        assert agent.instruction is None

    def test_with_instruction(self):
        bus = EventBus(); bus.start()
        agent = Agent(
            event_bus=bus,
            provider='deepseek', model='deepseek-chat',
            instruction='You are a helpful assistant.',
            http_options={'timeout': 10},
        )
        bus.stop()
        assert agent.instruction == 'You are a helpful assistant.'

    def test_with_tools(self):
        bus = EventBus(); bus.start()
        t = Tool(name='ping', description='ping', tool=lambda: 'pong')
        agent = Agent(
            event_bus=bus,
            provider='deepseek', model='deepseek-chat',
            tools=[t], http_options={'timeout': 10},
        )
        bus.stop()
        assert agent.tools is not None
        assert 'ping' in agent.tools


class TestAgentClear:
    def test_clear_empties_client_messages(self):
        bus = EventBus(); bus.start()
        agent = Agent(
            event_bus=bus,
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        agent.client.messages.append({'role': 'user', 'content': 'hello'})
        assert len(agent.client.messages) > 0
        agent.clear()
        bus.stop()
        assert agent.client.messages == []


class TestAgentStateDict:
    def test_from_state_dict(self):
        bus = EventBus(); bus.start()
        agent = Agent(
            event_bus=bus,
            name='original', provider='deepseek', model='deepseek-chat',
            instruction='original', http_options={'timeout': 10},
        )
        agent.client.messages = [
            {'role': 'system', 'content': 'original'},
            {'role': 'user', 'content': 'test'},
        ]

        state = agent.state_dict()
        restored = Agent.from_state_dict(state, event_bus=bus)
        bus.stop()
        assert restored.name == 'original'
        assert restored.instruction == 'original'
        assert restored.provider == 'deepseek'
        assert restored.model == 'deepseek-chat'
        assert len(restored.client.messages) == 2