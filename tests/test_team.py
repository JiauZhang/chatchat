from chatchat.agent import AgentConfig, Agent
from chatchat.team import Team, TeamConfig
from chatchat.actor import ResourcePool, Action
from chatchat.task import Task, TaskStatus
from chatchat.event import EventBus
from chatchat.tool import Tool
from queue import Queue
import time
import pytest


def make_agent_config(name, **kwargs):
    return AgentConfig(
        name=name, provider='deepseek', model='deepseek-chat',
        **kwargs,
    )


class TestTeamCreation:
    def test_basic_creation(self):
        bus = EventBus()
        team = Team(name='test', event_bus=bus,
                    leader=make_agent_config('leader'))
        assert team.name == 'test'
        assert team.leader.name == 'leader'
        assert team._members == []
        assert hasattr(team, '_tasks')
        assert team._tasks == {}

    def test_with_members(self):
        bus = EventBus()
        team = Team(name='test', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('a1'), make_agent_config('a2')])
        assert len(team._members) == 2
        assert team._members[0].name == 'a1'
        assert team._members[1].name == 'a2'

    def test_with_sub_team(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[TeamConfig(name='sub', leader=make_agent_config('sl'))])
        assert len(team._members) == 1
        assert team.is_leaf is False

    def test_add_member(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.add_member(make_agent_config('a'))
        assert len(team._members) == 1
        assert team._members[0].name == 'a'

    def test_agent_then_team_raises(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.add_member(make_agent_config('a'))
        with pytest.raises(TypeError, match='不能混合'):
            team.add_member(TeamConfig(name='sub', leader=make_agent_config('sl')))

    def test_leader_property(self):
        bus = EventBus()
        team = Team(name='test', event_bus=bus,
                    leader=make_agent_config('leader'))
        assert team.leader.name == 'leader'

    def test_members_property(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('a1'), make_agent_config('a2')])
        assert [m.name for m in team.members] == ['a1', 'a2']

    def test_sub_team_members_property(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[TeamConfig(name='sub1', leader=make_agent_config('sl1'))])
        assert [m.name for m in team.members] == ['sl1']

    def test_is_leaf_empty(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus, leader=make_agent_config('l'))
        assert team.is_leaf is True

    def test_is_leaf_with_agents(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('l'),
                    members=[make_agent_config('a')])
        assert team.is_leaf is True

    def test_context_manager(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        with team as t:
            assert t is team
            assert t.is_running
        assert not t.is_running

    def test_lifecycle_start_stops_members(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('a1')])
        team.start()
        assert team.is_running
        assert team.leader.is_running
        assert team.find_member('a1').is_running
        team.stop()
        assert not team.is_running


class TestFindMember:
    def test_find_leader(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        assert team.find_member('leader').name == 'leader'

    def test_find_agent_member(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('alice')])
        assert team.find_member('alice').name == 'alice'

    def test_find_sub_team_leader(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('l'),
                    members=[TeamConfig(name='sub', leader=make_agent_config('sub_leader'))])
        assert team.find_member('sub_leader').name == 'sub_leader'

    def test_find_nonexistent(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('l'))
        assert team.find_member('nobody') is None


class TestTaskManagement:
    def test_create_task(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        result = team._create_task('写一个报告')
        assert '任务已创建' in result
        assert len(team._tasks) == 1
        task_id = list(team._tasks.keys())[0]
        assert team._tasks[task_id].status == TaskStatus.CREATED

    def test_create_task_with_depends(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team._create_task('task A')
        task_a_id = list(team._tasks.keys())[0]
        team._create_task('task B', depends_on=[task_a_id])
        task_b_id = [k for k in team._tasks if k != task_a_id][0]
        assert team._tasks[task_b_id].depends_on == [task_a_id]

    def test_get_task(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team._create_task('测试任务')
        task_id = list(team._tasks.keys())[0]
        result = team._get_task(task_id)
        assert task_id in result
        assert '测试任务' in result

    def test_get_task_not_found(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        result = team._get_task('nonexistent')
        assert '未找到' in result

    def test_list_tasks(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team._create_task('任务1')
        team._create_task('任务2')
        result = team._list_tasks()
        assert '2 个任务' in result

    def test_list_tasks_empty(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        assert team._list_tasks() == '暂无任务'

    def test_update_task(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team._create_task('测试')
        task_id = list(team._tasks.keys())[0]
        team._update_task(task_id, 'in_progress')
        assert team._tasks[task_id].status == TaskStatus.IN_PROGRESS
        team._update_task(task_id, 'completed', result='完成')
        assert team._tasks[task_id].status == TaskStatus.COMPLETED
        assert team._tasks[task_id].result == '完成'

    def test_update_task_not_found(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        result = team._update_task('nonexistent', 'completed')
        assert '未找到' in result

    def test_assign_task_non_blocking(self, monkeypatch):
        """_assign_task 是非阻塞的，返回后任务状态为 ASSIGNED。"""
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('worker')])
        team.start()
        team._create_task('do something')
        task_id = list(team._tasks.keys())[0]
        worker = team.find_member('worker')

        monkeypatch.setattr(worker, '_handle_chat', lambda msg: 'done!')
        result = team._assign_task(task_id=task_id, member_name='worker')
        assert '已分配' in result
        assert team._tasks[task_id].status == TaskStatus.ASSIGNED
        assert team._tasks[task_id].owner == 'worker'
        team.stop()

    def test_assign_task_propagates_task_entity(self, monkeypatch):
        """Task 实体通过 mailbox 传递到目标，目标收到后加入自己的 _tasks。"""
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('worker')])
        team.start()
        team._create_task('do something')
        task_id = list(team._tasks.keys())[0]
        worker = team.find_member('worker')
        original_task = team._tasks[task_id]

        monkeypatch.setattr(worker, '_handle_chat', lambda msg: 'done!')
        team._assign_task(task_id=task_id, member_name='worker')

        # 给 mailbox 线程一点时间处理 task_assigned
        time.sleep(0.1)
        assert task_id in worker._tasks
        assert worker._tasks[task_id] is original_task
        team.stop()

    def test_assign_task_not_found(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('l'))
        result = team._assign_task(task_id='nonexistent', member_name='nobody')
        assert '未找到任务' in result

    def test_assign_task_unmet_dependency(self, monkeypatch):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('worker')])
        team.start()
        team._create_task('前置任务')
        dep_id = list(team._tasks.keys())[0]
        team._create_task('后续任务', depends_on=[dep_id])
        task_b_id = [k for k in team._tasks if k != dep_id][0]
        result = team._assign_task(task_id=task_b_id, member_name='worker')
        assert '依赖' in result
        assert '未完成' in result
        team.stop()

    def test_assign_task_met_dependency(self, monkeypatch):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('worker')])
        team.start()
        team._create_task('前置任务')
        dep_id = list(team._tasks.keys())[0]
        team._create_task('后续任务', depends_on=[dep_id])
        task_b_id = [k for k in team._tasks if k != dep_id][0]
        team._tasks[dep_id].status = TaskStatus.COMPLETED

        worker = team.find_member('worker')
        monkeypatch.setattr(worker, '_handle_chat', lambda msg: 'done!')
        result = team._assign_task(task_id=task_b_id, member_name='worker')
        assert '已分配' in result
        team.stop()

    def test_assign_task_member_not_found(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team._create_task('test')
        task_id = list(team._tasks.keys())[0]
        result = team._assign_task(task_id=task_id, member_name='nobody')
        assert '未找到成员' in result

    def test_assign_task_to_sub_team_propagates_task(self, monkeypatch):
        """分配到子 Team leader 时，Task 实体进入子 Team 的 _tasks。"""
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[TeamConfig(name='sub', leader=make_agent_config('sl'))])
        team.start()
        team._create_task('sub task')
        task_id = list(team._tasks.keys())[0]
        sub_team = team._members[0]
        original_task = team._tasks[task_id]

        monkeypatch.setattr(sub_team.leader, '_handle_chat', lambda msg: 'done!')
        team._assign_task(task_id=task_id, member_name='sl')

        time.sleep(0.1)
        assert task_id in sub_team._tasks
        assert sub_team._tasks[task_id] is original_task
        team.stop()


class TestSendMessage:
    def test_send_message_non_blocking(self):
        """send_message 是非阻塞的，调用后立即返回。"""
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('alice'), make_agent_config('bob')])
        alice = team.find_member('alice')
        result = team._send_message('alice', 'hello')
        assert '消息已发送' in result
        # 消息被放入目标 mailbox（非阻塞，无需等待回复）
        assert not alice._mailbox.empty()

    def test_send_message_member_not_found(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        result = team._send_message('nobody', 'hello')
        assert '未找到成员' in result


class TestAgentToolsInjection:
    def test_leader_has_management_tools(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        leader = team.leader
        assert leader.tools is not None
        assert 'assign_task' in leader.tools
        assert 'create_task' in leader.tools
        assert 'send_message' in leader.tools
        assert 'update_task' in leader.tools
        assert 'call_meeting' in leader.tools
        assert 'list_members' in leader.tools

    def test_member_has_task_and_communication_tools(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('worker')])
        worker = team.find_member('worker')
        assert worker.tools is not None
        assert 'update_task' in worker.tools
        assert 'send_message' in worker.tools
        assert 'get_task' in worker.tools
        assert 'list_tasks' in worker.tools


class TestChatEvents:
    def test_chat_emits_team_events(self, monkeypatch):
        events = []
        bus = EventBus()
        bus.start()
        bus.subscribe('team:*', lambda e: events.append((e.topic, e.data)))
        team = Team(name='my_team', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.start()
        monkeypatch.setattr(team.leader, '_handle_chat', lambda msg: 'ok')
        team.chat('hello')
        team.stop()
        bus.stop()

        assert len(events) >= 2
        assert events[0][0] == 'team:start'
        assert events[0][1]['name'] == 'my_team'
        assert events[0][1]['message'] == 'hello'
        assert events[0][1]['mode'] == 'supervisor'
        assert events[-1][0] == 'team:end'
        assert events[-1][1]['content'] == 'ok'
        assert events[-1][1]['mode'] == 'supervisor'


class TestNewTools:
    def test_list_members_empty(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        assert team._list_members() == '暂无成员'

    def test_list_members_with_agents(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('alice'), make_agent_config('bob')])
        result = team._list_members()
        assert 'alice' in result
        assert 'bob' in result

    def test_list_members_with_sub_team(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[TeamConfig(name='sub', leader=make_agent_config('sl'))])
        result = team._list_members()
        assert 'sub' in result
        assert 'sl' in result

    def test_call_meeting_no_members(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        result = team._call_meeting('讨论方案')
        assert '没有下属' in result

    def test_call_meeting_with_members(self, monkeypatch):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    members=[make_agent_config('alice'), make_agent_config('bob')])
        team.start()
        alice = team.find_member('alice')
        bob = team.find_member('bob')
        monkeypatch.setattr(alice, '_handle_chat', lambda msg: '我同意')
        monkeypatch.setattr(bob, '_handle_chat', lambda msg: '我没问题')
        result = team._call_meeting('讨论方案')
        assert '会议主题' in result
        assert 'alice' in result
        assert 'bob' in result
        team.stop()

    def test_agent_receives_task_assigned(self, monkeypatch):
        """Agent 收到 task_assigned 后，Task 加入 _tasks 并触发处理。"""
        bus = EventBus()
        agent = Agent(
            event_bus=bus, name='worker',
            provider='deepseek', model='deepseek-chat',
            http_options={'timeout': 10},
        )
        agent.start()
        task = Task(description='测试任务')
        called = []
        monkeypatch.setattr(agent, '_handle_chat', lambda msg: called.append(msg) or 'done')
        action = Action(type='task_assigned', payload=task)
        result = agent._on_message(action)
        assert task.id in agent._tasks
        assert agent._tasks[task.id] is task
        assert len(called) == 1
        assert '测试任务' in called[0]
        agent.stop()

    def test_team_receives_task_assigned(self, monkeypatch):
        """Team 收到 task_assigned 后，Task 加入 _tasks 并委托给 leader。"""
        bus = EventBus()
        team = Team(name='sub', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.start()
        task = Task(description='子团队任务')
        called = []
        monkeypatch.setattr(team.leader, '_handle_chat', lambda msg: called.append(msg) or 'done')
        action = Action(type='task_assigned', payload=task)
        result = team._on_message(action)
        assert task.id in team._tasks
        assert team._tasks[task.id] is task
        assert len(called) == 1
        assert '子团队任务' in called[0]
        team.stop()


class TestDynamicMembers:
    def test_spawn_agent_creates_member(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.start()
        result = team._spawn_agent(name='worker', instruction='you are a worker')
        assert '成功创建' in result
        assert team.find_member('worker') is not None
        team.stop()

    def test_spawn_agent_resource_limit(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    resource_pool=ResourcePool(max_agents=1))
        team.start()
        team._spawn_agent(name='a1', instruction='w1')
        result = team._spawn_agent(name='a2', instruction='w2')
        assert '资源已耗尽' in result
        assert team.find_member('a2') is None
        team.stop()

    def test_create_team_creates_sub_team(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'))
        team.start()
        result = team._create_team(name='sub', leader_name='sl', leader_instruction='you are sl')
        assert '成功创建' in result
        assert team.find_member('sl') is not None
        team.stop()

    def test_create_team_resource_limit(self):
        bus = EventBus()
        team = Team(name='t', event_bus=bus,
                    leader=make_agent_config('leader'),
                    resource_pool=ResourcePool(max_teams=1))
        team.start()
        team._create_team(name='sub1', leader_name='sl1', leader_instruction='w1')
        result = team._create_team(name='sub2', leader_name='sl2', leader_instruction='w2')
        assert '资源已耗尽' in result
        assert team.find_member('sl2') is None
        team.stop()