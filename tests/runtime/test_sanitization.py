"""Rule values and teammate text follow the reference's untrusted-input
handling: tool lists split on commas and spaces outside braces, and free text
entering the model context is stripped of hidden Unicode."""
from chatchat.team.mailbox import Message, format_teammate_batch
from chatchat.knowledge.rules import split_items
from chatchat.runtime.sanitization import sanitize_unicode


def test_rule_values_split_on_commas_and_spaces_outside_braces():
    assert split_items('Edit, Write Bash') == ['Edit', 'Write', 'Bash']
    assert split_items('src/{a,b}.py src/c.py') == ['src/{a,b}.py',
                                                    'src/c.py']
    assert split_items('Edit') == ['Edit']
    assert split_items('') == []


def test_sanitization_strips_hidden_characters_but_keeps_text():
    dirty = 'ok\u200bay\u202ereversed\U000e0050tag\ufeff'
    assert sanitize_unicode(dirty) == 'okayreversedtag'


def test_sanitization_normalizes_composed_characters():
    assert sanitize_unicode('ﬁ') == 'fi'
    assert sanitize_unicode('plain text') == 'plain text'


def test_teammate_batch_sanitizes_the_message_text():
    batch = format_teammate_batch([
        Message(from_='bot', text='hi\u200bthere'),
        Message(from_='bot2', text='plain'),
    ])
    assert ('<teammate-message teammate_id="bot">\nhithere\n'
            '</teammate-message>') in batch
    assert 'plain' in batch
