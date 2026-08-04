import time
import pytest
from chatchat.scheduler import Scheduler
from chatchat.worker import Worker, WorkerConfig
from chatchat.message import ID, Message


class TestWorkerLifecycle:
    def test_create_without_agent(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='no_llm'), s)
        assert w.name == 'no_llm'
        assert w._agent is None
        assert not w.is_running

    def test_create_with_agent(self):
        s = Scheduler()
        w = Worker(WorkerConfig(
            name='test', provider='deepseek', model='deepseek-chat',
        ), s)
        assert w.name == 'test'
        assert w._agent is not None
        assert not w.is_running

    def test_start_stop(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        assert not w.is_running
        w.start()
        assert w.is_running
        w.stop()
        assert not w.is_running

    def test_start_stop_multiple(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        w.start()
        w.stop()
        w.start()
        assert w.is_running
        w.stop()
        assert not w.is_running


class TestWorkerHandleMessage:
    def test_text_without_agent(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        msg = Message(sender=ID(), recipient=w.id, type='text', payload='hello')
        result = w.handle_message(msg)
        assert 'no LLM capability' in result

    def test_signal_stop(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='signal', subtype='stop')
        result = w.handle_message(msg)
        assert result == 'stopped'
        assert not w.is_running

    def test_request_ping(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        msg = Message(sender=ID(), recipient=w.id, type='request', subtype='ping')
        result = w.handle_message(msg)
        assert result == 'pong'

    def test_request_status(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='request', subtype='status')
        result = w.handle_message(msg)
        assert result['name'] == 'test'
        assert result['running'] is True
        assert result['has_agent'] is False
        w.stop()


class TestWorkerWithScheduler:
    def test_send_to_worker(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        s.register(w)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='request', subtype='ping')
        reply = s.request(msg, timeout=5)
        assert reply.payload == 'pong'
        w.stop()

    def test_request_to_worker(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        s.register(w)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='request', subtype='status')
        reply = s.request(msg, timeout=5)
        assert reply.payload['name'] == 'test'
        assert reply.payload['running'] is True
        w.stop()

    def test_signal_stop_via_scheduler(self):
        s = Scheduler()
        w = Worker(WorkerConfig(name='test'), s)
        s.register(w)
        w.start()
        assert w.is_running
        s.stop(w.id)
        time.sleep(0.2)
        assert not w.is_running

    def test_send_to_unregistered(self):
        s = Scheduler()
        msg = Message(sender=ID(), recipient=ID(uid='nowhere', kind='worker'), type='text')
        s.send(msg)
        assert True

    def test_create_agent_via_scheduler(self):
        s = Scheduler()
        wid = s.create_agent(WorkerConfig(
            name='via_scheduler', provider='deepseek', model='deepseek-chat',
        ))
        assert wid.kind == 'worker'
        assert wid.name == 'via_scheduler'
        w = s.lookup(wid)
        assert w is not None
        assert w._agent is not None
        s.stop(wid)

    def test_multiple_workers(self):
        s = Scheduler()
        w1 = Worker(WorkerConfig(name='a'), s)
        w2 = Worker(WorkerConfig(name='b'), s)
        s.register(w1)
        s.register(w2)
        w1.start()
        w2.start()

        msg1 = Message(sender=ID(), recipient=w1.id, type='request', subtype='ping')
        msg2 = Message(sender=ID(), recipient=w2.id, type='request', subtype='ping')
        r1 = s.request(msg1, timeout=5)
        r2 = s.request(msg2, timeout=5)
        assert r1.payload == 'pong'
        assert r2.payload == 'pong'
        w1.stop()
        w2.stop()

    def test_worker_chat_nonstream(self, monkeypatch):
        s = Scheduler()
        w = Worker(WorkerConfig(
            name='chatty', provider='deepseek', model='deepseek-chat',
            stream=False,
        ), s)
        s.register(w)
        w.start()
        assert w._agent is not None

        monkeypatch.setattr(w._agent.client, 'chat', lambda *a, **kw: type('R', (), {
            'choices': [type('C', (), {
                'message': type('M', (), {'content': 'hi back', 'tool_calls': None})(),
            })()],
        })())

        msg = Message(sender=ID(), recipient=w.id, type='text', payload='hello')
        reply = s.request(msg, timeout=10)
        assert reply.payload == 'hi back'
        w.stop()