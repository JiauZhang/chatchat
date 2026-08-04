import time
import pytest
from chatchat.scheduler import Scheduler
from chatchat.worker import Worker, WorkerConfig
from chatchat.team import Team, TeamConfig
from chatchat.message import ID, Message


def make_worker_config(name, **kwargs):
    return WorkerConfig(
        name=name, provider='deepseek', model='deepseek-chat',
        **kwargs,
    )


class TestTeamCreation:
    def test_basic_creation(self):
        s = Scheduler()
        team = Team(TeamConfig(name='test', leader=make_worker_config('leader')), s)
        assert team.id.name == 'test'
        assert team.leader.name == 'leader'
        assert len(team._members) == 0

    def test_with_members(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='test', leader=make_worker_config('leader'),
            members=[make_worker_config('a1'), make_worker_config('a2')],
        ), s)
        assert len(team._members) == 2
        assert team._members[0].name == 'a1'
        assert team._members[1].name == 'a2'

    def test_with_sub_team(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[TeamConfig(name='sub', leader=make_worker_config('sl'))],
        ), s)
        assert len(team._members) == 1
        assert isinstance(team._members[0], Team)

    def test_add_member(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        team.add_member(make_worker_config('a'))
        assert len(team._members) == 1
        assert team._members[0].name == 'a'

    def test_leader_property(self):
        s = Scheduler()
        team = Team(TeamConfig(name='test', leader=make_worker_config('leader')), s)
        assert team.leader.name == 'leader'

    def test_members_property(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('a1'), make_worker_config('a2')],
        ), s)
        assert [m.name for m in team.members] == ['a1', 'a2']

    def test_sub_team_members_property(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[TeamConfig(name='sub1', leader=make_worker_config('sl1'))],
        ), s)
        assert [m.name for m in team.members] == ['sl1']


class TestTeamLifecycle:
    def test_start_stop(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('a1')],
        ), s)
        team.start()
        assert team.is_running
        assert team.leader.is_running
        assert team.find_member('a1').is_running
        team.stop()
        assert not team.is_running

    def test_start_stop_sub_team(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[TeamConfig(name='sub', leader=make_worker_config('sl'))],
        ), s)
        team.start()
        assert team.is_running
        sub = team._members[0]
        assert sub.is_running
        assert sub.leader.is_running
        team.stop()
        assert not team.is_running


class TestFindMember:
    def test_find_leader(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        assert team.find_member('leader').name == 'leader'

    def test_find_agent_member(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('alice')],
        ), s)
        assert team.find_member('alice').name == 'alice'

    def test_find_sub_team_leader(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('l'),
            members=[TeamConfig(name='sub', leader=make_worker_config('sub_leader'))],
        ), s)
        assert team.find_member('sub_leader').name == 'sub_leader'

    def test_find_nonexistent(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('l')), s)
        assert team.find_member('nobody') is None


class TestLeaderTools:
    def test_list_members_empty(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        result = team._list_members()
        assert '暂无成员' in result

    def test_list_members_with_agents(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('alice'), make_worker_config('bob')],
        ), s)
        result = team._list_members()
        assert 'alice' in result
        assert 'bob' in result
        assert 'leader' in result

    def test_list_members_with_sub_team(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[TeamConfig(name='sub', leader=make_worker_config('sl'))],
        ), s)
        result = team._list_members()
        assert 'sub' in result
        assert 'sl' in result

    def test_send_msg_non_blocking(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('alice')],
        ), s)
        team.start()
        result = team._send_msg('alice', 'hello')
        assert '消息已发送' in result
        team.stop()

    def test_send_msg_member_not_found(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        result = team._send_msg('nobody', 'hello')
        assert '未找到成员' in result

    def test_assign_task(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('worker')],
        ), s)
        team.start()
        result = team._assign_task(task_id='t1', description='do something', member_name='worker')
        assert '已分配' in result
        assert 't1' in result
        team.stop()

    def test_assign_task_member_not_found(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        result = team._assign_task(task_id='t1', description='test', member_name='nobody')
        assert '未找到成员' in result

    def test_create_agent(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        team.start()
        result = team._create_agent(name='newbie', instruction='you are new')
        assert '成功创建' in result
        assert team.find_member('newbie') is not None
        team.stop()

    def test_create_team(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        team.start()
        result = team._create_team(name='sub', leader_name='sl', leader_instruction='you are sl')
        assert '成功创建' in result
        assert team.find_member('sl') is not None
        team.stop()


class TestToolInjection:
    def test_leader_has_tools(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        leader = team.leader
        assert leader._agent is not None
        assert leader._agent.tools is not None
        assert 'list_members' in leader._agent.tools
        assert 'send_msg' in leader._agent.tools
        assert 'assign_task' in leader._agent.tools
        assert 'create_agent' in leader._agent.tools
        assert 'create_team' in leader._agent.tools


class TestHandleMessage:
    def test_text_routes_to_leader(self, monkeypatch):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        called = []
        monkeypatch.setattr(team._leader, 'handle_message', lambda msg: called.append(msg) or 'ok')
        msg = Message(sender=ID(), recipient=team.id, type='text', payload='hello')
        result = team.handle_message(msg)
        assert result == 'ok'
        assert len(called) == 1

    def test_request_list_members(self):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader'),
            members=[make_worker_config('alice')],
        ), s)
        msg = Message(sender=ID(), recipient=team.id, type='request', subtype='list_members')
        result = team.handle_message(msg)
        assert 'leader' in result['members']
        assert 'alice' in result['members']

    def test_request_status(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        msg = Message(sender=ID(), recipient=team.id, type='request', subtype='status')
        result = team.handle_message(msg)
        assert result['name'] == 't'
        assert result['leader'] == 'leader'


class TestIntegration:
    def test_send_to_team_via_scheduler(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader')), s)
        s.register(team)
        team.start()
        msg = Message(sender=ID(), recipient=team.id, type='request', subtype='status')
        reply = s.request(msg, timeout=5)
        assert reply.payload['name'] == 't'
        team.stop()

    def test_leader_chat_nonstream(self, monkeypatch):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_worker_config('leader', stream=False)), s)
        s.register(team)
        team.start()
        leader = team.leader

        monkeypatch.setattr(leader._agent.client, 'chat', lambda *a, **kw: type('R', (), {
            'choices': [type('C', (), {
                'message': type('M', (), {'content': 'done', 'tool_calls': None})(),
            })()],
        })())

        msg = Message(sender=ID(), recipient=team.id, type='text', payload='hello')
        reply = s.request(msg, timeout=10)
        assert reply.payload == 'done'
        team.stop()

    def test_member_receives_task(self, monkeypatch):
        s = Scheduler()
        team = Team(TeamConfig(
            name='t', leader=make_worker_config('leader', stream=False),
            members=[make_worker_config('worker', stream=False)],
        ), s)
        s.register(team)
        team.start()
        worker = team.find_member('worker')

        received = []
        monkeypatch.setattr(worker._agent.client, 'chat', lambda *a, **kw: (
            received.append(a[0][0]['content']) if a and a[0] else None,
            type('R', (), {
                'choices': [type('C', (), {
                    'message': type('M', (), {'content': 'ok', 'tool_calls': None})(),
                })()],
            })()
        )[-1])

        team._assign_task(task_id='t1', description='测试任务', member_name='worker')
        time.sleep(0.2)
        assert len(received) > 0
        assert '测试任务' in str(received)
        team.stop()