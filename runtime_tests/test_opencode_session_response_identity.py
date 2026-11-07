"""Actual HTTP evidence builder with a controlled client; no transport or Host."""
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from runtime.codex_driver import BindingIdentity, DriverJournal
from runtime.opencode_driver import OpenCodeNativeDriver, digest


@pytest.mark.parametrize("method,path,status,value,expected", [
    ("POST", "/session", 200, {"id": "ses_actual", "title": "private title"}, "ses_actual"),
    ("POST", "/session", 201, {"id": "ses_actual"}, "ses_actual"),
    ("POST", "/session", 503, {"id": "ses_not_created"}, None),
    ("POST", "/session", 200, {"id": "wrong-provider-id"}, None),
    ("POST", "/session", 200, {"id": "ses_" + "a" * 251}, None),
    ("POST", "/session", 200, ["not a session response"], None),
    ("GET", "/session/ses_actual", 200, {"id": "ses_actual"}, None),
    ("POST", "/session/ses_actual/prompt_async", 200, {"id": "ses_actual"}, None),
])
def test_session_identity_comes_only_from_a_successful_bounded_actual_create_response(tmp_path, method, path, status, value, expected):
    journal = DriverJournal(tmp_path / "driver.sqlite")
    driver = object.__new__(OpenCodeNativeDriver)
    driver.journal, driver.http_timeout = journal, 5
    driver.identity = BindingIdentity("node", "boot", "runtime", "capacity", "slot", 1)
    driver._identity = asdict(driver.identity)
    driver._auth = lambda _operation: None  # This unit checks response evidence, not authority.
    driver.client = SimpleNamespace(endpoint="http://127.0.0.1:1",
        request=lambda *_args, **_kwargs: (status, value))
    operation = SimpleNamespace(operation_id="controlled-original", read_only=False, remaining=lambda _clock: 5)
    driver.clock = None
    assert driver._http(operation, method, path) == (status, value)
    with journal._connect() as connection:
        rows = connection.execute("SELECT body FROM driver_events WHERE operation_id=? AND kind='http_response'",
                                  (operation.operation_id,)).fetchall()
    assert len(rows) == 1
    evidence = json.loads(rows[0][0])
    assert evidence.get("native_session_id") == expected and evidence["body_digest"] == digest(value)
    assert "private title" not in str(evidence) and "title" not in evidence
