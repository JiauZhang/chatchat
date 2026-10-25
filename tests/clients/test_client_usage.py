from chatchat.client import Client, MockClient


def _client():
    return Client("agnes/agnes-3.0-flash", instruction="You are helpful.")


def test_a_client_that_has_not_spoken_yet_still_has_usage_to_read():
    """The usage of a call is read when the answer is recorded, and a call
    that never reached the model - one that waited for a rate limit and gave
    up - still has to leave numbers behind that someone can read."""
    client = _client()
    assert client._last_usage.to_dict() == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_tokens_details": None,
    }


def test_the_client_that_stands_in_for_a_model_answers_the_same_way():
    """The client that talks to a model and the one that stands in for it are
    read the same way; a difference between them shows up as a failure only
    when the model is real."""
    real = _client()
    fake = MockClient()
    assert hasattr(real, "_last_usage") == hasattr(fake, "_last_usage")
    assert hasattr(real, "_last_response_items") == hasattr(fake, "_last_response_items")
