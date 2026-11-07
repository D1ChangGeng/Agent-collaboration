"""Recovery facade and mounted handler unit checks; no PG/Native qualification."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from runtime.client_contracts import ClientContracts
from runtime.communication_client_recovery import ClientRecoveryService
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_http import PREFIX, CommunicationHttpError, create_communication_app
from runtime.errors import AuthorizationDenied
from runtime.project_service import ProjectService

NOW = "2026-11-06T00:00:00Z"
BODY = {"action": "inspect", "expected_revision": 4, "reason": "Inspect this registered receiver"}


def operation():
    return {"operation_id": "receiver-recovery-original", "kind": "recovery", "state": "completed",
            "message_handle": None, "receiver_ref": "receiver/one", "binding_epoch": 4,
            "effect_state": "committed", "reason_code": "receiver_unknown", "evidence_refs": [],
            "revision": 2, "created_at": NOW, "updated_at": NOW}


@pytest.fixture
def facade(monkeypatch):
    calls = []
    result = operation()
    state = SimpleNamespace(submit_error=None, advance_error=None, result=result)

    class Recovery:
        def __init__(self, projects):
            assert projects is state.projects

        def submit(self, *args):
            calls.append(("submit", args))
            if state.submit_error:
                raise state.submit_error
            return result | {"state": "queued", "revision": 1}

        def advance(self, *args):
            calls.append(("advance", args))
            if state.advance_error:
                raise state.advance_error
            return state.result

    monkeypatch.setattr("runtime.communication_client_recovery.ReceiverRecoveryOperations", Recovery)
    service = object.__new__(CommunicationClientService)
    service.project_service = state.projects = object()
    service.credential = "synthetic-bearer"
    state.client, state.calls = service, calls
    return state


def test_recovery_reuses_the_existing_command_before_advancing_its_exact_operation(facade):
    f = facade
    result = f.client.recover_receiver("p", "receiver/one", BODY, client_request_id="stable-key")
    assert result == operation()
    assert f.calls == [
        ("submit", ("p", "receiver/one", BODY, "stable-key", "synthetic-bearer")),
        ("advance", ("p", "receiver-recovery-original", "synthetic-bearer"))]
    assert issubclass(CommunicationClientService, ClientRecoveryService)


def test_rejected_admission_does_not_advance_or_invent_an_accepted_operation(facade):
    f = facade
    f.submit_error = AuthorizationDenied("actor", "grant")
    with pytest.raises(AuthorizationDenied):
        f.client.recover_receiver("p", "receiver/one", BODY, client_request_id="stable-key")
    assert [call[0] for call in f.calls] == ["submit"]


@pytest.mark.parametrize("action,effect", [("inspect", "committed"), ("reconcile", "committed"),
                                         ("retry_delivery", "unknown"), ("resume_receiver", "unknown")])
def test_post_commit_failure_retains_the_original_operation_and_conservative_effect(facade, action, effect):
    f = facade
    f.advance_error = PermissionError("private revoked credential details")
    body = BODY | {"action": action}
    if action in {"reconcile", "retry_delivery"}:
        body["operation_ref"] = "original-delivery"
    with pytest.raises(CommunicationHttpError) as caught:
        f.client.recover_receiver("p", "receiver/one", body, client_request_id="stable-key")
    error = caught.value
    assert error.status_code == 503 and error.retryable is False
    assert error.operation_ref == "receiver-recovery-original" and error.effect_state == effect
    assert "private" not in str(error)
    assert [call[0] for call in f.calls] == ["submit", "advance"]


def test_inconsistent_post_commit_result_does_not_return_another_operation(facade):
    facade.result = operation() | {"operation_id": "foreign-operation"}
    with pytest.raises(CommunicationHttpError) as caught:
        facade.client.recover_receiver("p", "receiver/one", BODY, client_request_id="stable-key")
    assert caught.value.operation_ref == "receiver-recovery-original"


@pytest.mark.parametrize("receiver", ["", " ", "bad\nreceiver", "a" * 513, None])
def test_invalid_receiver_reference_has_no_admission_effect(facade, receiver):
    with pytest.raises(CommunicationHttpError):
        facade.client.recover_receiver("p", receiver, BODY, client_request_id="stable-key")
    assert facade.calls == []


def test_blank_reason_is_rejected_before_accepting_a_command(facade):
    with pytest.raises(CommunicationHttpError) as caught:
        facade.client.recover_receiver("p", "receiver/one", BODY | {"reason": " \n "}, client_request_id="key")
    assert caught.value.code == "invalid_argument" and caught.value.effect_state == "none"
    assert facade.calls == []


def inline(coroutine):
    """Drive handlers whose unit dependencies complete synchronously, without I/O."""
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError("Unit handler unexpectedly requested external scheduling")


@pytest.fixture
def handler(monkeypatch):
    import runtime.communication_http as http

    state = SimpleNamespace(authenticated=True, calls=[], failure=None)
    projects = object.__new__(ProjectService)

    def authenticate(credential):
        if credential != "synthetic-bearer" or not state.authenticated:
            raise PermissionError("private authentication failure")

    projects.service = SimpleNamespace(authenticate=authenticate)

    async def run(method, *args, **kwargs):
        return method(*args, **kwargs)

    monkeypatch.setattr(http, "_run", run)

    def recover(project, receiver, body, *, client_request_id):
        state.calls.append((project, receiver, body, client_request_id))
        if state.failure:
            raise state.failure
        return operation()

    app = create_communication_app(lambda _request: (projects, "synthetic-bearer"),
        service_factory=lambda *_args: SimpleNamespace(recover_receiver=recover))
    route = next(route for route in app.routes if getattr(route, "name", None) == "recover_receiver")
    state.route = route

    def request(*, body=None, headers=None):
        encoded = json.dumps(BODY if body is None else body).encode()
        actual = [(b"authorization", b"Bearer synthetic-bearer"), (b"content-type", b"application/json"),
                  (b"idempotency-key", b"stable-key")] if headers is None else headers

        async def receive():
            return {"type": "http.request", "body": encoded, "more_body": False}

        req = Request({"type": "http", "method": "POST", "path": PREFIX + "/projects/p/receivers/receiver/one/actions",
            "headers": actual, "query_string": b"", "path_params": {"project_id": "p", "receiver_id": "receiver/one"}}, receive)
        req.state.effect_state, req.state.operation_ref = "none", None
        return req

    state.request = request
    return state


def test_mounted_action_accepts_exact_body_and_idempotency_key_and_returns_202(handler):
    f = handler
    request = f.request()
    assert f.route.path == PREFIX + "/projects/{project_id}/receivers/{receiver_id:path}/actions"
    response = inline(f.route.endpoint("p", "receiver/one", request))
    assert response.status_code == 202 and json.loads(response.body) == operation()
    assert request.state.operation_ref == "receiver-recovery-original" and request.state.effect_state == "committed"
    assert f.calls == [("p", "receiver/one", BODY, "stable-key")]
    ClientContracts().validate("Operation", json.loads(response.body))


@pytest.mark.parametrize("defect", ["missing_key", "duplicate_key", "if_match", "malformed_body", "missing_auth"])
def test_mounted_action_rejects_invalid_framing_before_admission(handler, defect):
    f = handler
    headers = [(b"authorization", b"Bearer synthetic-bearer"), (b"content-type", b"application/json")]
    if defect != "missing_key":
        headers.append((b"idempotency-key", b"stable-key"))
    if defect == "duplicate_key":
        headers.append((b"idempotency-key", b"another-key"))
    if defect == "if_match":
        headers.append((b"if-match", b'"4"'))
    if defect == "missing_auth":
        headers = [item for item in headers if item[0] != b"authorization"]
    request = f.request(body={"action": "inspect"} if defect == "malformed_body" else None, headers=headers)
    with pytest.raises((CommunicationHttpError, PermissionError)):
        inline(f.route.endpoint("p", "receiver/one", request))
    assert f.calls == [] and request.state.effect_state == "none"


def test_mounted_action_keeps_none_effect_for_precommit_domain_rejection(handler):
    handler.failure = AuthorizationDenied("actor", "grant")
    request = handler.request()
    with pytest.raises(AuthorizationDenied):
        inline(handler.route.endpoint("p", "receiver/one", request))
    assert request.state.effect_state == "none"


def test_mounted_action_preserves_postcommit_operation_when_return_authentication_expires(handler):
    original = handler.route.endpoint
    request = handler.request()
    # The command result is known; result() preserves its handle before the
    # final authenticate check. No command is retried by the HTTP wrapper.
    calls = handler.calls
    real_append = calls.append

    class RevokeOnCall(list):
        def append(self, value):
            real_append(value)
            handler.authenticated = False

    handler.calls = RevokeOnCall()
    with pytest.raises(PermissionError):
        inline(original("p", "receiver/one", request))
    assert len(calls) == 1
    assert request.state.operation_ref == "receiver-recovery-original" and request.state.effect_state == "committed"
