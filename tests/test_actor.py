from typing import Any
from chatchat.actor import Actor, Action, ResourcePool
from chatchat.event import EventBus
import pytest


class TestAction:
    def test_create_action(self):
        action = Action(type='chat', payload='hello')
        assert action.type == 'chat'
        assert action.payload == 'hello'
        assert action.sender == ''
        assert action.metadata == {}

    def test_action_with_sender(self):
        action = Action(type='task', payload={'x': 1}, sender='alice')
        assert action.type == 'task'
        assert action.payload == {'x': 1}
        assert action.sender == 'alice'


class EchoActor(Actor):
    def _on_message(self, action: Action) -> Any:
        return f'echo: {action.payload}'


class TestActor:
    def test_run_requires_started(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        with pytest.raises(RuntimeError, match='Actor is not started'):
            actor.run(Action(type='chat', payload='test'))

    def test_run_returns_result(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        result = actor.run(Action(type='chat', payload='hello'))
        actor.stop()
        assert result == 'echo: hello'

    def test_run_multiple_sequential(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        assert actor.run(Action(type='chat', payload='a')) == 'echo: a'
        assert actor.run(Action(type='chat', payload='b')) == 'echo: b'
        assert actor.run(Action(type='chat', payload='c')) == 'echo: c'
        actor.stop()

    def test_arun_returns_result(self):
        import asyncio
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        result = asyncio.run(actor.arun(Action(type='chat', payload='hello')))
        actor.stop()
        assert result == 'echo: hello'

    def test_run_preserves_order(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        r1 = actor.run(Action(type='chat', payload='first'))
        r2 = actor.run(Action(type='chat', payload='second'))
        actor.stop()
        assert r1 == 'echo: first'
        assert r2 == 'echo: second'

    def test_start_stop_lifecycle(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        assert actor._thread is None
        actor.start()
        assert actor._thread is not None
        assert actor._thread.is_alive()
        actor.stop()
        assert actor._thread is None

    def test_start_stop_multiple(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        actor.stop()
        actor.start()
        assert actor._thread is not None
        assert actor._thread.is_alive()
        actor.stop()
        assert actor._thread is None

    def test_run_after_stop_raises(self):
        bus = EventBus()
        actor = EchoActor(name='echo', event_bus=bus)
        actor.start()
        actor.stop()
        with pytest.raises(RuntimeError, match='Actor is not started'):
            actor.run(Action(type='chat', payload='test'))

    def test_exception_propagation(self):
        bus = EventBus()
        base = Actor(name='base', event_bus=bus)
        base.start()
        with pytest.raises(NotImplementedError):
            base.run(Action(type='chat', payload='test'))
        base.stop()


class TestResourcePool:
    def test_default_limits(self):
        pool = ResourcePool()
        assert pool.max_agents == 10
        assert pool.max_teams == 5
        assert pool.used_agents == 0
        assert pool.used_teams == 0

    def test_can_spawn_within_limits(self):
        pool = ResourcePool(max_agents=2, max_teams=1)
        assert pool.can_spawn_agent()
        assert pool.can_spawn_team()
        pool.used_agents = 2
        pool.used_teams = 1
        assert not pool.can_spawn_agent()
        assert not pool.can_spawn_team()

    def test_custom_limits(self):
        pool = ResourcePool(max_agents=5, max_teams=3)
        assert pool.max_agents == 5
        assert pool.max_teams == 3