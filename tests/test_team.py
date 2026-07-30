from chatchat.agent import Agent
from chatchat.team import Team
from chatchat.event import EventBus
import pytest


def make_agent(name, bus):
    return Agent(
        event_bus=bus, name=name, provider='deepseek',
        model='deepseek-chat', http_options={'timeout': 10},
    )


class TestTeamCreation:
    def test_basic_creation(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='test', leader=leader, event_bus=bus)
        assert team.name == 'test'
        assert team.leader is leader
        assert team.max_depth == 5
        assert team._members == []
        assert team.is_leaf is True

    def test_custom_max_depth(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='test', leader=leader, event_bus=bus, max_depth=3)
        assert team.max_depth == 3


class TestAddMember:
    def test_add_agent(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        a = make_agent('a', bus)
        team.add_member(a)
        assert team._members == [a]
        assert team.is_leaf is True

    def test_add_team(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        sub_leader = make_agent('sub_leader', bus)
        sub_team = Team(name='sub', leader=sub_leader, event_bus=bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(sub_team)
        assert team._members == [sub_team]
        assert team.is_leaf is False

    def test_agent_then_team_raises(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(make_agent('a', bus))
        sub = Team(name='sub', leader=make_agent('sl', bus), event_bus=bus)
        with pytest.raises(TypeError, match='不能混合'):
            team.add_member(sub)

    def test_team_then_agent_raises(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        sub = Team(name='sub', leader=make_agent('sl', bus), event_bus=bus)
        team.add_member(sub)
        with pytest.raises(TypeError, match='不能混合'):
            team.add_member(make_agent('a', bus))


class TestMembersProperty:
    def test_leaf_members(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        a1 = make_agent('a1', bus)
        a2 = make_agent('a2', bus)
        team.add_member(a1)
        team.add_member(a2)
        assert team.members == [a1, a2]

    def test_intermediate_members(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        sl1 = make_agent('sl1', bus)
        sl2 = make_agent('sl2', bus)
        sub1 = Team(name='sub1', leader=sl1, event_bus=bus)
        sub2 = Team(name='sub2', leader=sl2, event_bus=bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(sub1)
        team.add_member(sub2)
        assert team.members == [sl1, sl2]


class TestIsLeaf:
    def test_empty_is_leaf(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        assert team.is_leaf is True

    def test_agent_members_is_leaf(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        team.add_member(make_agent('a', bus))
        assert team.is_leaf is True

    def test_team_members_not_leaf(self):
        bus = EventBus()
        sub = Team(name='sub', leader=make_agent('sl', bus), event_bus=bus)
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        team.add_member(sub)
        assert team.is_leaf is False


class TestFindMember:
    def test_find_leader(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        assert team.find_member('leader') is leader

    def test_find_agent_member(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        a = make_agent('alice', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(a)
        assert team.find_member('alice') is a

    def test_find_sub_team_leader(self):
        bus = EventBus()
        sl = make_agent('sub_leader', bus)
        sub = Team(name='sub', leader=sl, event_bus=bus)
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        team.add_member(sub)
        result = team.find_member('sub_leader')
        assert result is sl

    def test_find_deep_nested_agent(self):
        bus = EventBus()
        sl = make_agent('sl', bus)
        worker = make_agent('deep_worker', bus)
        sub = Team(name='sub', leader=sl, event_bus=bus)
        sub.add_member(worker)
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        team.add_member(sub)
        result = team.find_member('deep_worker')
        assert result is worker

    def test_find_multilevel_nested(self):
        bus = EventBus()
        # Team: root -> mid -> leaf
        leaf_worker = make_agent('leaf_worker', bus)
        leaf = Team(name='leaf', leader=make_agent('leaf_l', bus), event_bus=bus)
        leaf.add_member(leaf_worker)
        mid = Team(name='mid', leader=make_agent('mid_l', bus), event_bus=bus)
        mid.add_member(leaf)
        root = Team(name='root', leader=make_agent('root_l', bus), event_bus=bus)
        root.add_member(mid)
        assert root.find_member('leaf_worker') is leaf_worker
        assert root.find_member('leaf_l') is leaf.leader
        assert root.find_member('mid_l') is mid.leader

    def test_find_nonexistent(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        assert team.find_member('nobody') is None


class TestContextManager:
    def test_context_manager(self):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        with team as t:
            assert t is team


class TestConsumeChat:
    def test_consume_string_result(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        a = make_agent('a', bus)
        monkeypatch.setattr(a, 'chat', lambda msg: f'processed: {msg}')
        result = team._consume_chat(a, 'hello')
        assert result == 'processed: hello'

    def test_consume_generator_result(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        a = make_agent('a', bus)

        def gen_chat(msg):
            yield 'chunk1'
            yield 'chunk2'
            yield 'chunk3'

        monkeypatch.setattr(a, 'chat', gen_chat)
        result = team._consume_chat(a, 'hello')
        assert result == 'chunk1chunk2chunk3'


class TestAssignTaskTool:
    def test_assign_task_finds_and_delegates(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        worker = make_agent('worker', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(worker)

        calls = []

        def fake_chat(msg):
            calls.append(msg)
            return f'done: {msg}'

        monkeypatch.setattr(worker, 'chat', fake_chat)
        result = team._assign_task(task='do something', member_name='worker')
        assert result == 'done: do something'
        assert calls == ['do something']

    def test_assign_task_not_found(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus)
        result = team._assign_task(task='x', member_name='nobody')
        assert '未找到成员' in result

    def test_assign_task_depth_exceeded(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus, max_depth=1)
        team._current_depth = 1
        result = team._assign_task(task='x', member_name='nobody')
        assert '超过限制' in result

    def test_assign_task_depth_restored_after_error(self):
        bus = EventBus()
        team = Team(name='t', leader=make_agent('l', bus), event_bus=bus, max_depth=1)
        # First call hits limit, depth should be restored
        result = team._assign_task(task='x', member_name='nobody')
        assert '未找到成员' in result
        assert team._current_depth == 0


class TestChat:
    def test_chat_injects_and_restores_tools(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        original_tools = leader.tools

        def fake_chat(msg):
            assert leader.tools is not None
            assert 'assign_task' in leader.tools
            return 'result'

        monkeypatch.setattr(leader, 'chat', fake_chat)
        result = team.chat('hello')
        assert result == 'result'
        assert leader.tools is original_tools

    def test_chat_emits_team_events(self, monkeypatch):
        events = []
        bus = EventBus()
        bus.start()
        bus.subscribe('team:*', lambda e: events.append((e.topic, e.data)))
        leader = make_agent('leader', bus)
        team = Team(name='my_team', leader=leader, event_bus=bus)
        monkeypatch.setattr(leader, 'chat', lambda msg: 'ok')
        team.chat('hello')
        bus.stop()
        assert len(events) >= 2
        assert events[0][0] == 'team:start'
        assert events[0][1]['name'] == 'my_team'
        assert events[0][1]['message'] == 'hello'
        assert events[0][1]['mode'] == 'supervisor'
        assert events[-1][0] == 'team:end'
        assert events[-1][1]['content'] == 'ok'
        assert events[-1][1]['mode'] == 'supervisor'


class TestPipeline:
    def test_pipeline_sequential(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        a1 = make_agent('a1', bus)
        a2 = make_agent('a2', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(a1)
        team.add_member(a2)

        order = []

        def fake_chat_a1(msg):
            order.append('a1')
            return 'a1 done'

        def fake_chat_a2(msg):
            order.append('a2')
            return 'a2 done'

        monkeypatch.setattr(a1, 'chat', fake_chat_a1)
        monkeypatch.setattr(a2, 'chat', fake_chat_a2)
        result = team.pipeline('start')
        assert result == 'a2 done'
        assert order == ['a1', 'a2']

    def test_pipeline_emits_team_events(self, monkeypatch):
        events = []
        bus = EventBus()
        bus.start()
        bus.subscribe('team:*', lambda e: events.append((e.topic, e.data)))
        leader = make_agent('leader', bus)
        a1 = make_agent('a1', bus)
        a2 = make_agent('a2', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(a1)
        team.add_member(a2)
        monkeypatch.setattr(a1, 'chat', lambda msg: 'a1 done')
        monkeypatch.setattr(a2, 'chat', lambda msg: 'a2 done')
        team.pipeline('start')
        bus.stop()
        assert events[0][0] == 'team:start'
        assert events[0][1]['mode'] == 'pipeline'
        assert events[1][0] == 'team:step'
        assert events[1][1]['content'].startswith('pipeline step')
        assert events[2][0] == 'team:step'
        assert events[2][1]['content'].startswith('pipeline step')
        assert events[3][0] == 'team:end'
        assert events[3][1]['mode'] == 'pipeline'


class TestParallel:
    def test_parallel_concurrent(self, monkeypatch):
        bus = EventBus()
        leader = make_agent('leader', bus)
        a1 = make_agent('a1', bus)
        a2 = make_agent('a2', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(a1)
        team.add_member(a2)

        monkeypatch.setattr(a1, 'chat', lambda msg: 'a1 result')
        monkeypatch.setattr(a2, 'chat', lambda msg: 'a2 result')
        result = team.parallel({'a1': 'task1', 'a2': 'task2'})
        assert result == {'a1': 'a1 result', 'a2': 'a2 result'}

    def test_parallel_with_find_member(self, monkeypatch):
        """Verify parallel looks up members by name via find_member"""
        bus = EventBus()
        leader = make_agent('leader', bus)
        worker = make_agent('worker', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(worker)

        monkeypatch.setattr(worker, 'chat', lambda msg: 'done')
        result = team.parallel({'worker': 'task'})
        assert result == {'worker': 'done'}

    def test_parallel_emits_team_events(self, monkeypatch):
        events = []
        bus = EventBus()
        bus.start()
        bus.subscribe('team:*', lambda e: events.append((e.topic, e.data)))
        leader = make_agent('leader', bus)
        worker = make_agent('worker', bus)
        team = Team(name='t', leader=leader, event_bus=bus)
        team.add_member(worker)
        monkeypatch.setattr(worker, 'chat', lambda msg: 'done')
        team.parallel({'worker': 'task'})
        bus.stop()
        assert events[0][0] == 'team:start'
        assert events[0][1]['mode'] == 'parallel'
        assert events[1][0] == 'team:step'
        assert events[1][1]['content'] == 'parallel done: worker'
        assert events[2][0] == 'team:end'
        assert events[2][1]['mode'] == 'parallel'