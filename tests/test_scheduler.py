import threading
from queue import Queue, Empty
from chatchat.scheduler import Scheduler, TimeoutError
from chatchat.message import Message, make_id


class EchoEntity:
    def __init__(self, name, scheduler=None):
        self.id = name
        self.kind = 'agent'
        self._mailbox = Queue()
        self._scheduler = scheduler
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def handle_message(self, msg):
        if msg.type == 'request':
            if msg.subtype == 'ping':
                return 'pong'
            if msg.subtype == 'echo':
                return msg.payload
        return msg.payload

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
                result = self.handle_message(msg)
                if result is not None and self._scheduler:
                    self._scheduler.reply(msg, result)
            except Empty:
                continue


class TestRegister:
    def test_register_entity(self):
        s = Scheduler()
        e = EchoEntity('alice')
        s.register(e)
        assert s.lookup(e.id).id == 'alice'

    def test_unregister_entity(self):
        s = Scheduler()
        e = EchoEntity('alice')
        s.register(e)
        s.unregister(e.id)
        assert s.lookup(e.id) is None


class TestSend:
    def test_send_message(self):
        s = Scheduler()
        e = EchoEntity('bob')
        s.register(e)
        s.send(Message(sender=make_id(), recipient=e.id, type='text', payload='hello'))
        msg = e._mailbox.get(timeout=1)
        assert msg.payload == 'hello'


class TestRequest:
    def test_request_reply(self):
        s = Scheduler()
        e = EchoEntity('bob', scheduler=s)
        s.register(e)
        e.start()
        reply = s.request(
            Message(sender=make_id(), recipient=e.id, type='request', subtype='ping'),
            timeout=5,
        )
        assert reply.payload == 'pong'

    def test_request_unknown_recipient(self):
        s = Scheduler()
        import pytest
        with pytest.raises(ValueError):
            s.request(Message(sender=make_id(), recipient='nobody', type='request', subtype='ping'))

    def test_request_timeout(self):
        s = Scheduler()
        e = EchoEntity('slow')
        s.register(e)
        import pytest
        with pytest.raises(TimeoutError):
            s.request(
                Message(sender=make_id(), recipient=e.id, type='request', subtype='echo', payload='hi'),
                timeout=0.01,
            )


class TestReply:
    def test_reply_resolves_pending_request(self):
        s = Scheduler()
        e = EchoEntity('helper', scheduler=s)
        s.register(e)
        e.start()
        reply = s.request(
            Message(sender=make_id(), recipient=e.id, type='request', subtype='echo', payload='hello'),
            timeout=5,
        )
        assert reply.payload == 'hello'
        e.stop()


class TestLookup:
    def test_lookup_by_name(self):
        s = Scheduler()
        e = EchoEntity('charlie')
        s.register(e)
        assert s.lookup_by_name('charlie') is e
        assert s.lookup_by_name('nobody') is None


class TestListEntities:
    def test_list_entities_with_kind(self):
        s = Scheduler()
        e = EchoEntity('dave')
        s.register(e)
        ids = s.list_entities(kind='agent')
        assert len(ids) >= 1
        assert 'dave' in ids


class TestStop:
    def test_stop_entity(self):
        s = Scheduler()
        from chatchat.agent import Agent, AgentConfig
        agent = Agent(AgentConfig(name='killme', provider='deepseek', model='deepseek-chat', http_options={'timeout': 10}))
        s.register(agent)
        agent.start()
        assert agent.is_running
        agent.stop()
        s.unregister(agent.id)
        assert not agent.is_running


class TestShutdown:
    def test_shutdown_clears_all(self):
        s = Scheduler()
        e = EchoEntity('dead')
        s.register(e)
        s.shutdown()
        assert s.list_entities() == []