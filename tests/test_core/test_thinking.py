"""How much a model may reason is a setting with three parts, not one flag."""
import pytest

from chatchat.core.thinking import Thinking


def test_the_default_asks_for_reasoning_without_a_number():
    assert Thinking().request() == {'thinking': {'type': 'enabled'}}


def test_switching_it_off_says_so_to_the_provider():
    assert Thinking('off').request() == {'thinking': {'type': 'disabled'}}


def test_a_model_that_picks_the_amount_itself_gets_no_budget():
    assert Thinking('adaptive').request() == {'thinking': {'type': 'adaptive'}}


def test_a_stated_budget_travels_with_the_request():
    assert Thinking('on', budget=8000).request() == {
        'thinking': {'type': 'enabled', 'budget_tokens': 8000}}


def test_an_effort_level_is_sent_on_its_own():
    assert Thinking(effort='high').request() == {
        'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}
    assert Thinking('off').request() == {'thinking': {'type': 'disabled'}}


def test_the_environment_can_set_the_budget_for_a_whole_run(monkeypatch):
    monkeypatch.setenv('MAX_THINKING_TOKENS', '12000')
    assert Thinking.from_env().budget == 12000
    assert Thinking.from_env().mode == 'on'
    monkeypatch.setenv('MAX_THINKING_TOKENS', '0')
    assert Thinking.from_env().mode == 'off'
    monkeypatch.delenv('MAX_THINKING_TOKENS')
    assert Thinking.from_env().budget == 0


def test_an_explicit_budget_beats_the_environment(monkeypatch):
    monkeypatch.setenv('MAX_THINKING_TOKENS', '12000')
    assert Thinking.from_env(budget=4000).budget == 4000


def test_a_mode_that_is_not_one_of_the_three_is_refused():
    with pytest.raises(ValueError):
        Thinking('sometimes')
    with pytest.raises(ValueError):
        Thinking(effort='extreme')
    with pytest.raises(ValueError):
        Thinking(budget=-1)


def test_the_reading_shows_what_is_actually_been_asked_for():
    assert Thinking('off').label() == 'thinking off'
    assert Thinking().label() == 'thinking on'
    assert Thinking('adaptive', effort='medium').label() == (
        'thinking adaptive \u00b7 effort medium')
    assert Thinking(budget=8000).label() == 'thinking 8000'
