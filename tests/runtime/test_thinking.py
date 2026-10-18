"""The unified thinking dial: one vocabulary, each protocol translates."""

import pytest

from chatchat.protocols.anthropic import payload as a_payload
from chatchat.protocols.openai import payload as o_payload
from chatchat.runtime.thinking import LEVELS, Thinking


def test_the_vocabulary_is_the_two_providers_common_dial():
    assert LEVELS == ("off", "low", "medium", "high", "xhigh")
    assert Thinking().level == "medium"


def test_a_level_outside_the_vocabulary_is_refused():
    with pytest.raises(ValueError):
        Thinking("sometimes")
    with pytest.raises(ValueError):
        Thinking("adaptive")


def test_the_reading_says_what_was_asked_for():
    assert Thinking("off").label() == "thinking off"
    assert Thinking("xhigh").label() == "thinking xhigh"


def test_anthropic_gets_adaptive_plus_effort():
    body = a_payload([{"role": "user", "content": "hi"}], None, "m1", Thinking("high"))
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}


def test_anthropic_off_sends_nothing():
    body = a_payload([{"role": "user", "content": "hi"}], None, "m1", Thinking("off"))
    assert "thinking" not in body
    assert "output_config" not in body


def test_openai_gets_the_effort_verbatim():
    body = o_payload([{"role": "user", "content": "hi"}], None, "m1", Thinking("low"))
    assert body["reasoning"] == {"effort": "low"}
    assert "thinking" not in o_payload([{"role": "user", "content": "hi"}], None, "m1", Thinking("off"))


def test_native_config_passes_through_untouched_and_wins():
    thinking = Thinking("low", native={"anthropic": {"thinking": {"type": "enabled", "budget_tokens": 4096}}})
    body = a_payload([{"role": "user", "content": "hi"}], None, "m1", thinking)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert "output_config" not in body
