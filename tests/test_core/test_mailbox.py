from chatchat.core.mailbox import (Mailbox, idle_notification,
                                   is_structured_protocol_message,
                                   format_teammate_batch)


def test_plain_text_not_protocol():
    assert is_structured_protocol_message('hello teammate') is None


def test_protocol_messages_detected():
    assert is_structured_protocol_message(
        idle_notification('researcher')) == 'idle_notification'


def test_invalid_json_not_protocol():
    assert is_structured_protocol_message('{not json') is None


def test_mailbox_write_unread_read():
    m = Mailbox()
    m.write('researcher', '研究结论')
    assert len(m.unread()) == 1
    m.mark_all_read()
    assert m.unread() == []


def test_mailbox_partial_read():
    m = Mailbox()
    m.write('r', 'm1')
    m.write('w', 'm2')
    msgs = m.unread()
    m.mark_read(msgs[0])
    assert len(m.unread()) == 1
    assert m.unread()[0].text == 'm2'


def test_format_batch_xml():
    m = Mailbox()
    m.write('r', 'hi')
    out = format_teammate_batch(m.unread())
    assert '<teammate_message teammate_id="r">' in out
    assert 'hi' in out