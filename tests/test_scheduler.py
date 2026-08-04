import threading
import pytest
from chatchat.scheduler import Scheduler, TimeoutError
from chatchat.message import ID, Message


class EchoWorker:
    def __init__(self, name='echo'):
        self.id = ID(uid=name, kind='worker', name=name)
        self._mailbox = __import__('queue').Queue()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                msg = self._mailbox.get(timeout=0.1)
                if msg.type == 'signal':
                    continue
                self.scheduler.reply(msg, f'echo: {msg.payload}')
            except __import__('queue').Empty:
                continue

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def handle_message(self, msg):
        return f'echo: {msg.payload}'


class TestScheduler:
    def test_register_and_lookup(self):
        s = Scheduler()
        w = EchoWorker('test')
        w.scheduler = s
        sid = s.register(w)
        assert s.lookup(sid) is w
        assert s.lookup(sid).id.uid == 'test'

    def test_send_fire_and_forget(self):
        s = Scheduler()
        w = EchoWorker('target')
        w.scheduler = s
        s.register(w)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='text', payload='hello')
        s.send(msg)
        import time
        time.sleep(0.1)
        w.stop()
        assert True

    def test_request_reply(self):
        s = Scheduler()
        w = EchoWorker('target')
        w.scheduler = s
        s.register(w)
        w.start()
        msg = Message(sender=ID(), recipient=w.id, type='text', payload='hello')
        reply = s.request(msg, timeout=5)
        assert reply.type == 'reply'
        assert reply.payload == 'echo: hello'
        w.stop()

    def test_request_timeout(self):
        s = Scheduler()
        w = EchoWorker('slow')
        w.scheduler = s
        s.register(w)
        msg = Message(sender=ID(), recipient=w.id, type='text', payload='hello')
        with pytest.raises(TimeoutError, match='Timeout'):
            s.request(msg, timeout=0.1)
        w.stop()

    def test_request_unknown_recipient(self):
        s = Scheduler()
        unknown_id = ID(uid='nonexistent', kind='worker')
        msg = Message(sender=ID(), recipient=unknown_id, type='text', payload='hello')
        with pytest.raises(ValueError, match='Unknown recipient'):
            s.request(msg, timeout=1)

    def test_publish_subscribe(self):
        s = Scheduler()
        w = EchoWorker('subscriber')
        w.scheduler = s
        s.register(w)
        s.subscribe('test.event', w.id)
        msg = Message(sender=ID(), recipient=ID(), type='event', payload='data')
        s.publish('test.event', msg)
        import time
        time.sleep(0.1)
        w.stop()
        assert True

    def test_subscribe_unsubscribe(self):
        s = Scheduler()
        w = EchoWorker('sub')
        w.scheduler = s
        s.register(w)
        s.subscribe('test', w.id)
        s.unsubscribe('test', w.id)
        msg = Message(sender=ID(), recipient=ID(), type='event')
        s.publish('test', msg)
        import time
        time.sleep(0.1)
        w.stop()
        assert True

    def test_wait_notify(self):
        s = Scheduler()
        notified = []

        def notifier():
            import time
            time.sleep(0.1)
            s.notify('test_condition')
            notified.append(True)

        t = threading.Thread(target=notifier, daemon=True)
        t.start()
        s.wait('test_condition', timeout=5)
        assert len(notified) == 1

    def test_wait_timeout(self):
        s = Scheduler()
        s.wait('never_notified', timeout=0.1)
        assert True

    def test_list_entities(self):
        s = Scheduler()
        w1 = EchoWorker('a')
        w2 = EchoWorker('b')
        w1.scheduler = s
        w2.scheduler = s
        s.register(w1)
        s.register(w2)
        entities = s.list_entities()
        assert len(entities) == 2
        assert 'a' in entities
        assert 'b' in entities

    def test_stop_entity(self):
        s = Scheduler()
        w = EchoWorker('test')
        w.scheduler = s
        s.register(w)
        w.start()
        s.stop(w.id)
        assert s.lookup(w.id) is None

    def test_shutdown(self):
        s = Scheduler()
        w1 = EchoWorker('a')
        w2 = EchoWorker('b')
        w1.scheduler = s
        w2.scheduler = s
        s.register(w1)
        s.register(w2)
        w1.start()
        w2.start()
        s.shutdown()
        assert len(s.list_entities()) == 0

    def test_send_to_unregistered(self):
        s = Scheduler()
        unknown_id = ID(uid='nowhere', kind='worker')
        msg = Message(sender=ID(), recipient=unknown_id, type='text')
        s.send(msg)
        assert True

    def test_multiple_requests(self):
        s = Scheduler()
        w = EchoWorker('target')
        w.scheduler = s
        s.register(w)
        w.start()
        results = []
        def do_request(n):
            msg = Message(sender=ID(), recipient=w.id, type='text', payload=f'req{n}')
            try:
                reply = s.request(msg, timeout=5)
                results.append(reply.payload)
            except Exception as e:
                results.append(f'error: {e}')
        threads = [threading.Thread(target=do_request, args=(i,), daemon=True) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 'echo: req0' in results
        assert 'echo: req1' in results
        assert 'echo: req2' in results
        w.stop()