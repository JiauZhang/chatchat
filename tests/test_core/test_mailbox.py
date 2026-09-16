import asyncio

from chatchat.core.inbox_poller import DEFAULT_INTERVAL, InboxPoller
from chatchat.core.mailbox import FileMailbox
from chatchat.core.team import Team
from chatchat.client import MockClient, ToolUse


def test_file_mailbox_persists_across_instances(tmp_path):
    path = tmp_path / 'inboxes' / 'worker.json'
    box = FileMailbox(path)
    box.write('lead', 'hello', summary='greeting')
    box.write('lead', 'second')

    reopened = FileMailbox(path)
    assert len(reopened) == 2
    texts = [m.text for m in reopened.unread()]
    assert texts == ['hello', 'second']
    reopened.mark_all_read()
    assert FileMailbox(path).unread() == []
    assert len(FileMailbox(path)) == 2


def test_file_mailbox_lockfile_serializes_writers(tmp_path):
    path = tmp_path / 'shared.json'
    writers = [FileMailbox(path) for _ in range(5)]
    for i, w in enumerate(writers):
        w.write(f'w{i}', f'm{i}')
    box = FileMailbox(path)
    assert [m.from_ for m in box.all()] == [f'w{i}' for i in range(5)]
    assert not path.with_suffix(path.suffix + '.lock').exists()


def test_poll_interval_is_half_second(tmp_path):
    assert DEFAULT_INTERVAL == 0.5


def test_unhandled_protocol_message_is_delivered_not_swallowed(tmp_path):
    seen = []

    async def respond(messages, tools=None, *, stream_cb=None):
        seen.append(' '.join(str(m.get('content')) for m in messages))
        return 'ok'

    async def main():
        team = Team('p', client_factory=lambda inst: MockClient(handler=respond))
        lead = team.lead
        lead.inbox.write('peer', '{"type": "idle_notification", "from": "peer"}')
        text = await lead.poller.poll_once()
        return text

    text = asyncio.run(main())
    assert text is not None and 'idle_notification' in text


def test_handled_protocol_message_is_routed(tmp_path):
    routed = []
    box = FileMailbox(tmp_path / 'a.json')
    box.write('peer', '{"type": "shutdown_request", "request_id": "r1"}')
    poller = InboxPoller(box, handlers={'shutdown_request':
                                        lambda m: routed.append(m)})
    text = asyncio.run(poller.poll_once())
    assert text is None and len(routed) == 1


def test_team_uses_file_mailboxes_under_dir(tmp_path):
    async def main():
        team = Team('fm', client_factory=lambda inst: MockClient(handler=None),
                    mailbox_dir=tmp_path / 'teams')
        return team.lead.inbox
    inbox = asyncio.run(main())
    assert isinstance(inbox, FileMailbox)
    assert 'fm' in str(inbox.path) and 'inboxes' in str(inbox.path)
