from chatchat.scheduler import Scheduler
from chatchat.agent import Agent, AgentConfig
from chatchat.team import Team, TeamConfig
from chatchat.message import ID, Message


def make_agent_config(name, **kwargs):
    return AgentConfig(
        name=name, provider='deepseek', model='deepseek-chat',
        **kwargs,
    )


class TestTeamCreation:
    def test_basic_creation(self):
        s = Scheduler()
        team = Team(TeamConfig(name='test', leader=make_agent_config('leader')), s)
        assert team.id.name == 'test'
        assert team.leader.name == 'leader'

    def test_leader_property(self):
        s = Scheduler()
        team = Team(TeamConfig(name='test', leader=make_agent_config('leader')), s)
        assert team.leader.name == 'leader'


class TestTeamLifecycle:
    def test_start_stop(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_agent_config('leader')), s)
        team.start()
        assert team.is_running
        assert team.leader.is_running
        team.stop()
        assert not team.is_running


class TestHandleMessage:
    def test_text_routes_to_leader(self, monkeypatch):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_agent_config('leader')), s)
        called = []
        monkeypatch.setattr(team._leader, 'handle_message', lambda msg: called.append(msg) or 'ok')
        msg = Message(sender=ID(), recipient=team.id, type='text', payload='hello')
        result = team.handle_message(msg)
        assert result == 'ok'
        assert len(called) == 1


class TestIntegration:
    def test_send_to_team_via_scheduler(self):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_agent_config('leader')), s)
        s.register(team)
        team.start()
        msg = Message(sender=ID(), recipient=team.id, type='request', subtype='status')
        reply = s.request(msg, timeout=5)
        assert reply.payload['name'] == 'leader'
        team.stop()

    def test_leader_chat(self, monkeypatch):
        s = Scheduler()
        team = Team(TeamConfig(name='t', leader=make_agent_config('leader')), s)
        s.register(team)
        team.start()
        leader = team.leader

        from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta
        def mock_chat(*a, **kw):
            yield ChatCompletionChunk(
                choices=[ChunkChoice(delta=Delta(content='done'), finish_reason='stop')],
            )

        monkeypatch.setattr(leader.client, 'chat', mock_chat)

        msg = Message(sender=ID(), recipient=team.id, type='text', payload='hello')
        reply = s.request(msg, timeout=10)
        assert reply.payload == 'done'
        team.stop()