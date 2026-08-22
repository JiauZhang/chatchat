import asyncio
import pytest
from chatchat.runtime import Scheduler, Event, RequestTimeoutError, make_id, parse_topic


class AsyncEcho:
    def __init__(self, name, scheduler=None):
        self.id = name
        self.kind = 'agent'
        self.mailbox: asyncio.Queue = asyncio.Queue()
        self._scheduler = scheduler
        self._stop = asyncio.Event()
        self._task = None

    async def start(self):
        self._stop.clear()
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()

    async def _process_loop(self):
        while not self._stop.is_set():
            try:
                ev = await asyncio.wait_for(self.mailbox.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            _, _, msg_type, subtype = parse_topic(ev.topic)
            if msg_type == 'request':
                if subtype == 'ping':
                    result = 'pong'
                elif subtype == 'echo':
                    result = ev.data
                else:
                    result = ev.data
                if ev.reply_to and self._scheduler:
                    await self._scheduler.reply(ev, result)


class TestRegister:
    def test_register_entity(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('alice', 'agent', q)
        assert eb.list_entities() == ['alice']

    def test_unregister_entity(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('alice', 'agent', q)
        eb.unregister_entity('alice')
        assert eb.list_entities() == []

    def test_duplicate_entity_id_raises(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('dup', 'agent', q)
        with pytest.raises(ValueError, match='Duplicate entity id'):
            eb.register_entity('dup', 'agent', q)

    def test_register_entity_with_name(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('e1', 'agent', q, name='friendly')
        eid, entry = eb.lookup('friendly')
        assert eid == 'e1'
        assert entry[1] is q


class TestSend:
    async def test_send_event(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('bob', 'agent', q)
        await eb.publish(Event(
            topic='entity:agent:bob:text', source=make_id(), data='hello',
        ))
        ev = await asyncio.wait_for(q.get(), timeout=1)
        assert ev.data == 'hello'


class TestRequest:
    async def test_request_reply(self):
        eb = Scheduler()
        e = AsyncEcho('bob', scheduler=eb)
        eb.register_entity('bob', 'agent', e.mailbox)
        await e.start()
        reply = await eb.request(
            source=make_id(), target_id='bob',
            topic='entity:agent:bob:request:ping', data='',
            timeout=5,
        )
        assert reply == 'pong'
        await e.stop()

    async def test_request_unknown_recipient(self):
        eb = Scheduler()
        with pytest.raises(ValueError, match='Unknown target'):
            await eb.request(
                source=make_id(), target_id='nobody',
                topic='entity:agent:nobody:request:ping', data='',
                timeout=0.01,
            )

    async def test_request_timeout(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('slow', 'agent', q)
        with pytest.raises(RequestTimeoutError):
            await eb.request(
                source=make_id(), target_id='slow',
                topic='entity:agent:slow:request:echo', data='hi',
                timeout=0.01,
            )


class TestReply:
    async def test_reply_resolves_pending_request(self):
        eb = Scheduler()
        e = AsyncEcho('helper', scheduler=eb)
        eb.register_entity('helper', 'agent', e.mailbox)
        await e.start()
        reply = await eb.request(
            source=make_id(), target_id='helper',
            topic='entity:agent:helper:request:echo', data='hello',
            timeout=5,
        )
        assert reply == 'hello'
        await e.stop()


class TestLookup:
    def test_lookup_by_name(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('charlie', 'agent', q)
        eid, entry = eb.lookup('charlie')
        assert eid == 'charlie'
        assert entry[1] is q
        eid, entry = eb.lookup('nobody')
        assert eid is None
        assert entry is None


class TestListEntities:
    def test_list_entities_with_kind(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('dave', 'agent', q)
        ids = eb.list_entities(kind='agent')
        assert len(ids) >= 1
        assert 'dave' in ids


class TestShutdown:
    def test_shutdown_clears_all(self):
        eb = Scheduler()
        q = asyncio.Queue()
        eb.register_entity('dead', 'agent', q)
        eb.shutdown()
        assert eb.list_entities() == []