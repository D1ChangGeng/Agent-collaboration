"""Actual encrypted page-token identity/namespace boundaries without a database."""
import json
import time

import pytest
from cryptography.fernet import Fernet

from runtime.communication_client_views import client_page_state, client_snapshot_token
from runtime.communication_http import CommunicationHttpError


@pytest.fixture(params=[
    ({"query": "authorized-query", "high": 33, "after": 12}, "after", 0),
    ({"query": "authorized-query", "high": 33, "before": 22, "personal": ["3", "4"]}, "before", None),
    ({"query": "authorized-query", "version": "current-receivers", "after": 1}, "after", 0),
    ({"query": "authorized-query", "high": 33, "version": ["1", "2"], "after": 11}, "after", 0),
])
def page(request):
    state, position, initial = request.param
    codec = Fernet(Fernet.generate_key())
    anchor = state | {position: initial}
    original = codec.encrypt(json.dumps(anchor).encode()).decode()
    return codec, state, position, initial, original


def test_validated_snapshot_is_returned_without_reminting_fernet_randomness(page, monkeypatch):
    codec, state, position, initial, original = page
    monkeypatch.setattr(codec, "encrypt", lambda *_args: pytest.fail("caller snapshot was reminted"))
    assert client_snapshot_token(codec, original, state["query"], state, position=position, initial=initial) == original


def test_initial_snapshot_starts_at_the_beginning_of_the_same_authorized_cut(page):
    codec, state, position, initial, _original = page
    token = client_snapshot_token(codec, None, state["query"], state, position=position, initial=initial)
    assert client_page_state(codec, token, state["query"]) == state | {position: initial}


def test_page_cursor_cannot_be_used_as_a_snapshot_anchor(page):
    codec, state, position, initial, _original = page
    cursor = codec.encrypt(json.dumps(state).encode()).decode()
    with pytest.raises(CommunicationHttpError) as caught:
        client_snapshot_token(codec, cursor, state["query"], state, position=position, initial=initial)
    assert caught.value.code == "cursor_invalid" and caught.value.effect_state == "none"


@pytest.mark.parametrize("defect", ["other_query", "other_cut", "other_metadata", "expired", "corrupt"])
def test_snapshot_must_match_the_complete_current_query_cut_and_expiry(page, defect):
    codec, state, position, initial, original = page
    if defect == "other_query":
        state = state | {"query": "another-principal-or-filter"}
    elif defect == "other_cut":
        key = "high" if "high" in state else "version"
        state = state | {key: 34 if key == "high" else "replaced-receivers"}
    elif defect == "other_metadata":
        key = "personal" if "personal" in state else "version" if "version" in state else "unexpected_scope"
        state = state | {key: "another-private-revision-or-scope"}
    elif defect == "expired":
        original = codec.encrypt_at_time(json.dumps(state | {position: initial}).encode(), int(time.time()) - 86401).decode()
    else:
        original = original[:-4] + "xxxx"
    with pytest.raises(CommunicationHttpError):
        client_snapshot_token(codec, original, state["query"], state, position=position, initial=initial)
