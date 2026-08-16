from chatchat import get_runtime, set_runtime, Runtime
from chatchat.agent import Agent, AgentConfig, create_agent
from chatchat.team import Team, TeamConfig, create_team
from chatchat.message import Message, make_id


class TestTeamCreation:
    def test_basic_creation(self):
        team = Team(TeamConfig(name='leader', provider='deepseek', model='deepseek-chat'))
        assert team.id == 'leader'
        assert team.leader.name == 'leader'

    def test_leader_property(self):
        team = Team(TeamConfig(name='leader', provider='deepseek', model='deepseek-chat'))
        assert team.leader.name == 'leader'


class TestTeamLifecycle:
    def test_start_stop(self):
        runtime = Runtime()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='deepseek', model='deepseek-chat'))
        assert team.is_running
        assert team.leader.is_running
        team.stop()
        assert not team.is_running


class TestHandleMessage:
    def test_text_routes_to_leader(self, monkeypatch):
        team = Team(TeamConfig(name='lead', provider='deepseek', model='deepseek-chat'))
        called = []
        monkeypatch.setattr(team._leader, 'handle_message', lambda msg: called.append(msg) or 'ok')
        msg = Message(sender=make_id(), recipient=team.id, type='text', payload='hello')
        result = team.handle_message(msg)
        assert result == 'ok'
        assert len(called) == 1


class TestIntegration:
    def test_send_to_team_via_scheduler(self):
        runtime = Runtime()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='deepseek', model='deepseek-chat'))
        msg = Message(sender=make_id(), recipient=team.id, type='request', subtype='status')
        reply = runtime.request(msg, timeout=5)
        assert reply.payload['name'] == 'lead'
        team.stop()

    def test_leader_chat(self, monkeypatch):
        runtime = Runtime()
        set_runtime(runtime)
        team = create_team(TeamConfig(name='lead', provider='deepseek', model='deepseek-chat'))
        leader = team.leader

        from chatchat.types import ChatCompletionChunk, ChunkChoice, Delta
        def mock_chat(*a, **kw):
            yield ChatCompletionChunk(
                choices=[ChunkChoice(delta=Delta(content='done'), finish_reason='stop')],
            )

        monkeypatch.setattr(leader.client, 'chat', mock_chat)

        msg = Message(sender=make_id(), recipient=team.id, type='text', payload='hello')
        reply = runtime.request(msg, timeout=10)
        assert reply.payload == 'done'
        team.stop()