"""HTTP framing/auth tests with explicit service fixtures, not DB qualification."""
from __future__ import annotations

import asyncio
import hashlib
import time
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from runtime.communication_client_queries import ClientProjection
from runtime.communication_http import (
    PREFIX,
    CommunicationHttpError,
    CommunicationHttpLimits,
    create_communication_app,
)
from runtime.errors import AuthorizationDenied, IdempotencyConflict, RevisionConflict
from runtime.project_service import ProjectService

TOKEN = "synthetic-bearer"
NOW = "2026-11-06T00:00:00Z"
PAGE = {"items": [], "page": {"next_cursor": None, "snapshot_id": None}}


def actor():
    return {"address": "client:p:synthetic", "principal_ref": "synthetic-principal", "level": "client",
            "agent_slot_id": None, "auth_revision": "synthetic-binding-1", "allowed_actions": ["send_message"]}


def message(handle="message:p:one", *, reply=False):
    text = "Synthetic peer reply" if reply else "Synthetic message"
    return {"message_handle": handle, "project_id": "p", "conversation_id": "synthetic-conversation",
        "sender": "collaborator:p:b" if reply else "client:p:synthetic", "to": "client:p:synthetic" if reply else "collaborator:p:b",
        "content": {"text": text, "offset": 0, "next_offset": None, "total_bytes": len(text.encode()),
                    "digest": hashlib.sha256(text.encode()).hexdigest()},
        "reply_to": ["message:p:one"] if reply else [], "attachment_refs": [], "conversation_sequence": "1",
        "committed_at": NOW, "revision": 1, "source": "acs_agent" if reply else "acs_client", "first_reply_handle": None}


def delivery():
    return {"message_handle": "message:p:one", "accepted_by_authority": True, "target_inbox_committed": False,
        "native": {"state": "unknown", "operation_ref": "synthetic-op", "binding_epoch": None,
                   "provider_generation": None, "evidence_ref": None, "native_input_ref": None, "reason_code": "synthetic_unknown"},
        "consumption": {"state": "unobservable", "semantics": "provider_input_consumed", "evidence_ref": None},
        "response": {"present": False, "message_handle": None}, "revision": 1}


class FixtureClientService:
    """Owns only controlled result fixtures and call recording; no Domain writes."""

    def __init__(self):
        self.calls, self.accepted = [], {}
        self.failure = None
        self.invalid_send_result = False
        self.incomplete = False

    def profile(self):
        self.calls.append(("profile",))
        return actor()

    def projects(self, **params):
        self.calls.append(("projects", params))
        return deepcopy(PAGE)

    def routes(self, project, **params):
        self.calls.append(("routes", project, params))
        return deepcopy(PAGE)

    def contacts(self, project, **params):
        self.calls.append(("contacts", project, params))
        return deepcopy(PAGE)

    def messages(self, project, **params):
        self.calls.append(("messages", project, params))
        if self.incomplete:
            return ClientProjection("MessagePage", {}, ("owning_revision",), core={"private": "never serialize this"})
        return deepcopy(PAGE)

    def read_message(self, project, handle, **params):
        self.calls.append(("read_message", project, handle, params))
        first = message("message:p:reply", reply=True)
        first["content"] = {"text": "", "offset": 0, "next_offset": 0, "total_bytes": 4, "digest": "a" * 64}
        return {"message": message(), "first_reply": first, "continuations": [
            {"message_handle": "message:p:reply", "offset": 0, "max_inline_bytes": 4}]}

    def delivery(self, project, handle):
        self.calls.append(("delivery", project, handle))
        return delivery()

    def wait(self, project, body):
        self.calls.append(("wait", project, deepcopy(body)))
        return {"wait": {"state": "timed_out", "satisfied_handles": [], "pending_handles": body["handles"]},
                "items": [delivery()], "continuations": []}

    def operation(self, reference, *, project_id):
        self.calls.append(("operation", reference, project_id))
        return {"operation_id": reference, "kind": "send", "state": "unknown", "message_handle": "message:p:one",
            "receiver_ref": None, "binding_epoch": None, "effect_state": "committed", "reason_code": None,
            "evidence_refs": [], "revision": 1, "created_at": NOW, "updated_at": NOW}

    def send(self, project, body, *, client_request_id):
        self.calls.append(("send", project, deepcopy(body), client_request_id))
        if self.failure is not None:
            raise self.failure
        if self.invalid_send_result:
            return {"operation_ref": "synthetic-committed-op", "duplicate": False}
        duplicate = client_request_id in self.accepted
        result = {"message": message(), "delivery": delivery(), "operation_ref": "synthetic-op", "duplicate": duplicate,
                  "wait": {"state": "timed_out" if body.get("response_mode") == "sync" else "not_requested",
                           "satisfied_handles": [], "pending_handles": ["message:p:one"] if body.get("response_mode") == "sync" else []}}
        self.accepted.setdefault(client_request_id, deepcopy(result))
        return result


def metadata(limits):
    return {"schema_version": "acs-client/1", "server_version": "synthetic_fixture", "authority_id": "synthetic-authority",
        "authority_incarnation": "synthetic-incarnation", "features": ["synthetic_fixture_http"],
        "limits": {"message_bytes": limits.message_bytes, "page_items": limits.page_items, "attachment_bytes": limits.attachment_bytes,
                   "attachment_count": limits.attachment_count, "event_replay_seconds": 0,
                   "attachment_total_bytes": limits.attachment_total_bytes, "attachment_staging_bytes": limits.attachment_staging_bytes,
                   "attachment_project_staging_bytes": limits.attachment_project_staging_bytes, "attachment_staging_seconds": limits.attachment_staging_seconds,
                   "native_link_count": limits.native_link_count, "native_link_history_revisions": limits.native_link_history_revisions,
                   "native_link_write_receipts": limits.native_link_write_receipts, "native_link_metadata_bytes": limits.native_link_metadata_bytes},
        "adapter_protocol": "acs-adapter/1", "event_protocol": "acs-event/1"}


@pytest.fixture
def http_boundary():
    state = SimpleNamespace(authorized=True, resolver_calls=0, auth_calls=[], factory_calls=0,
                            credential=TOKEN, service=FixtureClientService(), limits=CommunicationHttpLimits())
    projects = object.__new__(ProjectService)

    def authenticate(token):
        state.auth_calls.append(token)
        if not state.authorized or token != TOKEN:
            raise PermissionError("synthetic secret must never be reflected: " + token)

    projects.service = SimpleNamespace(authenticate=authenticate)
    state.projects = projects

    async def resolve(_request):
        state.resolver_calls += 1
        admitted = getattr(getattr(projects, "token_authorization", None), "admit_request", None)
        if callable(admitted):
            admitted()
        return projects, state.credential

    def factory(_projects, credential):
        assert _projects is projects and credential == TOKEN
        state.factory_calls += 1
        return state.service

    def app(*, limits=None, meta=True):
        current = limits or state.limits
        return create_communication_app(resolve, service_factory=factory, limits=current,
                                        public_meta=metadata(current) if meta else None)

    state.app = app
    return state


def request(app, method="GET", path="/profile", *, authenticated=True, **kwargs):
    async def run():
        headers = {"Authorization": "Bearer " + TOKEN} if authenticated else {}
        headers.update(kwargs.pop("headers", {}))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test") as client:
            return await client.request(method, PREFIX + path, headers=headers, **kwargs)
    return asyncio.run(run())


def post(state, body=None, *, key="original-key", **kwargs):
    headers = kwargs.pop("headers", {})
    if key is not None:
        headers["Idempotency-Key"] = key
    return request(state.app(), "POST", "/projects/p/messages", json=body or {"to": "collaborator:p:b", "content": "hello"},
                   headers=headers, **kwargs)


def test_meta_is_public_and_only_reports_explicit_matching_configuration(http_boundary):
    f = http_boundary
    response = request(f.app(), path="/meta", authenticated=False)
    assert response.status_code == 200 and response.json()["features"] == ["synthetic_fixture_http"]
    assert f.resolver_calls == f.factory_calls == 0 and f.auth_calls == []
    unavailable = request(f.app(meta=False), path="/meta", authenticated=False)
    assert unavailable.status_code == 503 and unavailable.json()["error"]["effect_state"] == "none"


@pytest.mark.parametrize("header", [None, "Basic synthetic", "Bearer", "Bearer a b", "Bearer bad\u00e9"])
def test_protected_routes_authenticate_before_body_or_parameter_validation(http_boundary, header):
    f = http_boundary
    headers = {} if header is None else {"Authorization": header}
    # httpx refuses non-ASCII header strings; bytes still exercise the ingress.
    if header and "\u00e9" in header:
        headers = {"Authorization": header.encode("utf-8")}
    response = request(f.app(), "POST", "/projects/p/messages?sender=forged", authenticated=False,
                       headers=headers, content="not-json")
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert f.resolver_calls == f.factory_calls == 0 and f.service.calls == []


def test_resolver_cannot_substitute_server_default_credential(http_boundary):
    f = http_boundary
    f.credential = "server-default-secret"
    response = request(f.app())
    assert response.status_code == 401 and f.auth_calls == [] and f.factory_calls == 0
    assert "server-default-secret" not in response.text


def test_current_project_authentication_runs_for_every_request(http_boundary):
    f = http_boundary
    assert request(f.app()).json() == actor()
    assert f.auth_calls == [TOKEN, TOKEN, TOKEN]
    f.authorized = False
    rejected = request(f.app())
    assert rejected.status_code == 401 and f.factory_calls == 1
    assert f.auth_calls == [TOKEN] * 4 and TOKEN not in rejected.text


def test_send_key_defaults_and_sync_timeout_preserve_one_service_action(http_boundary):
    f = http_boundary
    body = {"to": "collaborator:p:b", "content": "ask", "response_mode": "sync", "wait_timeout_seconds": 0}
    first = post(f, body)
    assert first.status_code == 201 and first.json()["wait"]["state"] == "timed_out"
    assert len(f.service.calls) == 1 and f.service.calls[0] == ("send", "p", body, "original-key")
    duplicate = post(f, body)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    assert duplicate.json()["operation_ref"] == first.json()["operation_ref"] and len(f.service.accepted) == 1


@pytest.mark.parametrize("field,value", [("sender", "forged-root"), ("actor", {"level": "root"}),
    ("principal_ref", "root"), ("agent_slot_id", "other"), ("project_id", "another-project"),
    ("client_request_id", "override-header"), ("activation", "steer"), ("response_mode", "blocking")])
def test_body_cannot_select_sender_identity_or_rewrite_send_contract(http_boundary, field, value):
    f = http_boundary
    response = post(f, {"to": "collaborator:p:b", "content": "literal text", field: value})
    assert response.status_code == 400 and response.json()["error"]["effect_state"] == "none"
    assert f.service.calls == []


@pytest.mark.parametrize("key", [None, "", "control\tcharacter", "x" * 201])
def test_stable_bounded_idempotency_header_is_required_before_send(http_boundary, key):
    f = http_boundary
    response = post(f, key=key)
    assert response.status_code == 400 and f.service.calls == []


def test_idempotency_header_is_opaque_and_not_trimmed_or_rewritten(http_boundary):
    f = http_boundary
    response = post(f, key="opaque key with spaces")
    assert response.status_code == 201
    assert f.service.calls[-1][-1] == "opaque key with spaces"


def test_utf8_and_json_byte_limits_reject_before_submission(http_boundary):
    f = http_boundary
    limits = CommunicationHttpLimits(message_bytes=7, json_bytes=1024)
    app = f.app(limits=limits)
    headers = {"Idempotency-Key": "unicode-limit"}
    accepted = request(app, "POST", "/projects/p/messages", json={"to": "collaborator:p:b", "content": "你🙂"}, headers=headers)
    assert accepted.status_code == 201
    rejected = request(app, "POST", "/projects/p/messages", json={"to": "collaborator:p:b", "content": "你🙂a"}, headers=headers)
    assert rejected.status_code == 413 and rejected.json()["error"]["effect_state"] == "none"
    assert len(f.service.calls) == 1
    oversized = request(app, "POST", "/projects/p/messages", content=b" " * 1025,
        headers={**headers, "Content-Type": "application/json"})
    assert oversized.status_code == 413 and len(f.service.calls) == 1


@pytest.mark.parametrize("raw", ['{"to":"a","to":"b","content":"text"}',
    '{"to":"a","content":"text","wait_timeout_seconds":NaN}', '[]', 'null',
    '{"to":"a","content":"\\ud800"}'])
def test_duplicate_nonfinite_nonobject_or_invalid_utf8_json_is_not_accepted(http_boundary, raw):
    f = http_boundary
    response = request(f.app(), "POST", "/projects/p/messages", content=raw,
                       headers={"Idempotency-Key": "malformed", "Content-Type": "application/json"})
    assert response.status_code == 400 and f.service.calls == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=true", "limit=1&limit=2", "sender=root", "cursor="])
def test_query_budgets_and_unknown_identity_parameters_are_strict(http_boundary, query):
    f = http_boundary
    response = request(f.app(), path="/projects?" + query)
    assert response.status_code == 400 and f.service.calls == []


@pytest.mark.parametrize("path,method", [("/projects", "projects"), ("/projects/p/routes", "routes"),
    ("/projects/p/contacts", "contacts"), ("/projects/p/messages", "messages")])
def test_query_routes_delegate_authenticated_scope_and_stable_page_fields(http_boundary, path, method):
    f = http_boundary
    response = request(f.app(), path=path + "?limit=2&cursor=opaque&snapshot_id=snapshot")
    assert response.status_code == 200 and response.json() == PAGE
    call = f.service.calls[-1]
    assert call[0] == method and call[-1] == {"limit": 2, "cursor": "opaque", "snapshot_id": "snapshot"}


@pytest.mark.parametrize("source_selection", ["", "&include_native_source=false"])
def test_read_continuation_zero_and_independent_reply_are_not_rewritten(http_boundary, source_selection):
    f = http_boundary
    response = request(f.app(), path="/projects/p/messages/message:p:one?offset=0&max_inline_bytes=1" + source_selection)
    assert response.status_code == 200
    assert response.json()["first_reply"]["content"]["next_offset"] == 0
    assert response.json()["continuations"] == [{"message_handle": "message:p:reply", "offset": 0, "max_inline_bytes": 4}]
    assert f.service.calls[-1] == ("read_message", "p", "message:p:one", {"offset": 0, "max_inline_bytes": 1})


def test_native_source_extension_is_passed_only_when_explicitly_selected(http_boundary):
    f = http_boundary
    response = request(f.app(), path="/projects/p/messages/message:p:one?include_native_source=true")
    assert response.status_code == 200
    assert f.service.calls[-1] == ("read_message", "p", "message:p:one",
        {"offset": 0, "max_inline_bytes": 16384, "include_native_source": True})


def test_wait_is_only_one_observation_and_operation_read_is_project_scoped(http_boundary):
    f = http_boundary
    waited = request(f.app(), "POST", "/projects/p/waits", json={"handles": ["message:p:one"], "timeout_seconds": 0})
    assert waited.status_code == 200 and waited.json()["wait"]["state"] == "timed_out"
    assert f.service.calls == [("wait", "p", {"handles": ["message:p:one"], "timeout_seconds": 0})]
    operation = request(f.app(), path="/projects/p/operations/synthetic-op")
    assert operation.status_code == 200 and f.service.calls[-1] == ("operation", "synthetic-op", "p")


def test_incomplete_legacy_projection_never_leaks_core_payload_as_target_dto(http_boundary):
    f = http_boundary
    f.service.incomplete = True
    response = request(f.app(), path="/projects/p/messages")
    assert response.status_code == 409 and response.json()["error"]["effect_state"] == "none"
    assert "never serialize" not in response.text


@pytest.mark.parametrize("failure,status,code", [(AuthorizationDenied("principal", "grant-secret"), 403, "authorization_denied"),
    (IdempotencyConflict("secret-key"), 409, "idempotency_conflict"), (RevisionConflict("private-target", 1, 2), 409, "revision_conflict")])
def test_service_errors_do_not_claim_no_effect_after_send_entry(http_boundary, failure, status, code):
    f = http_boundary
    f.service.failure = failure
    response = post(f)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert response.json()["error"]["effect_state"] == "unknown"
    assert "grant-secret" not in response.text and "secret-key" not in response.text and "private-target" not in response.text


def test_post_commit_error_retains_original_operation_and_effect_state(http_boundary):
    f = http_boundary
    f.service.failure = CommunicationHttpError("receiver_unavailable", "Observation is unavailable.", status_code=503,
        effect_state="committed", operation_ref="original-operation")
    response = post(f)
    assert response.status_code == 503
    assert response.json()["error"]["effect_state"] == "committed"
    assert response.json()["error"]["operation_ref"] == "original-operation"
    assert len(f.service.calls) == 1


def test_failed_output_serialization_cannot_erase_committed_send(http_boundary):
    f = http_boundary
    f.service.invalid_send_result = True
    response = post(f)
    assert response.status_code == 503 and response.json()["error"]["effect_state"] == "committed"
    assert response.json()["error"]["operation_ref"] == "synthetic-committed-op"


def test_unknown_backend_exception_is_redacted_and_never_retried(http_boundary):
    f = http_boundary
    f.service.failure = OSError("postgres://private-dsn " + TOKEN)
    response = post(f)
    assert response.status_code == 503 and response.json()["error"]["effect_state"] == "unknown"
    assert "private-dsn" not in response.text and TOKEN not in response.text
    assert len(f.service.calls) == 1


def test_quota_failure_is_explicitly_uncommitted_with_retry_after(http_boundary):
    f = http_boundary
    f.service.failure = CommunicationHttpError("quota_exceeded", "Rejected before acceptance.", status_code=429,
        retryable=True, effect_state="none", retry_after=3)
    response = post(f)
    assert response.status_code == 429 and response.headers["retry-after"] == "3"
    assert response.json()["error"]["effect_state"] == "none"


@pytest.mark.parametrize("method,path,status", [("GET", "/unimplemented", 404), ("DELETE", "/profile", 405)])
def test_router_failures_also_use_redacted_problem_shape(http_boundary, method, path, status):
    response = request(http_boundary.app(), method, path, authenticated=False)
    assert response.status_code == status
    assert set(response.json()) == {"error", "request_id"}
    assert response.json()["error"]["effect_state"] == "none"


def test_path_reference_budget_is_checked_after_auth_before_service_factory(http_boundary):
    f = http_boundary
    response = request(f.app(), path="/projects/" + "x" * 513 + "/messages")
    assert response.status_code == 400 and f.auth_calls == [TOKEN]
    assert f.factory_calls == 0 and f.service.calls == []


class FixtureAuthorization:
    """Accelerated bounded observation; never performs OAuth or network I/O."""

    def __init__(self, *, fail_after=None):
        self.verifier = SimpleNamespace(settings=SimpleNamespace(authorization_refresh_seconds=0.2))
        self.valid, self.checked_at = True, time.monotonic()
        self.calls, self.fail_after = 0, fail_after

    def admit_request(self):
        # Real OAuth introspection observes the credential at request admission,
        # after application construction, rather than at test-object creation.
        self.checked_at = time.monotonic()

    async def refresh(self):
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            # The boundary must invalidate even when the refresher fails before
            # its own normal invalidation logic, e.g. a transport exception.
            raise OSError("private introspection failure " + TOKEN)
        self.checked_at = time.monotonic()

    def authenticate(self, token):
        if not self.valid or time.monotonic() - self.checked_at > 0.2 or token != TOKEN:
            raise PermissionError("private expired observation " + TOKEN)


def refreshing_authorization(state, *, fail_after=None):
    authorization = FixtureAuthorization(fail_after=fail_after)
    original = state.projects.service.authenticate

    def authenticate(token):
        original(token)
        authorization.authenticate(token)

    state.projects.token_authorization = authorization
    state.projects.service.authenticate = authenticate
    state.service.project_service = state.projects
    return authorization


def test_long_worker_method_keeps_auth_observation_fresh_and_stops_refresh_after_response(http_boundary):
    f = http_boundary
    authorization = refreshing_authorization(f)
    observations = []

    def slow_profile():
        for _ in range(7):
            time.sleep(0.05)
            f.projects.service.authenticate(TOKEN)
            observations.append(authorization.calls)
        return actor()

    f.service.profile = slow_profile

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f.app()), base_url="http://synthetic.test") as client:
            response = await client.get(PREFIX + "/profile", headers={"Authorization": "Bearer " + TOKEN})
            stopped_at = authorization.calls
            await asyncio.sleep(0.12)
            return response, stopped_at

    response, stopped_at = asyncio.run(run())
    assert response.status_code == 200 and response.json() == actor()
    assert len(observations) == 7 and observations[-1] > observations[0]
    assert stopped_at >= 5 and authorization.calls == stopped_at


def test_refresh_failure_invalidates_without_cancelling_worker_or_disclosing_body(http_boundary):
    f = http_boundary
    authorization = refreshing_authorization(f, fail_after=3)
    completed = []

    def slow_profile():
        time.sleep(0.25)
        completed.append(True)
        return {**actor(), "principal_ref": "private-body-must-not-be-returned"}

    f.service.profile = slow_profile
    response = request(f.app())
    assert response.status_code == 401 and response.json()["error"]["effect_state"] == "none"
    assert authorization.valid is False and authorization.calls == 3 and completed == [True]
    assert "private-body" not in response.text and "private introspection" not in response.text and TOKEN not in response.text


def test_refresh_failure_after_send_commit_preserves_handle_and_never_replays(http_boundary):
    f = http_boundary
    authorization = refreshing_authorization(f, fail_after=3)
    original = f.service.send
    completed, committed = [], Event()
    original_refresh = authorization.refresh

    async def refresh_after_commit():
        if authorization.calls + 1 >= authorization.fail_after:
            assert await asyncio.to_thread(committed.wait, 5), "fixture must establish a real accepted send before authorization loss"
        await original_refresh()

    authorization.refresh = refresh_after_commit

    def slow_send(project, body, *, client_request_id):
        value = original(project, body, client_request_id=client_request_id)
        committed.set()
        time.sleep(0.25)
        completed.append(True)
        return value

    f.service.send = slow_send
    response = post(f, {"to": "collaborator:p:b", "content": "private-send-body", "response_mode": "sync"})
    error = response.json()["error"]
    assert response.status_code == 401 and error["effect_state"] == "committed"
    assert error["operation_ref"] == "synthetic-op"
    assert authorization.valid is False and completed == [True]
    assert len(f.service.calls) == len(f.service.accepted) == 1
    assert "private-send-body" not in response.text and "Synthetic message" not in response.text and TOKEN not in response.text


def test_synthetic_oauth_observation_begins_at_request_admission_after_application_setup(http_boundary):
    f = http_boundary
    authorization = refreshing_authorization(f)
    app = f.app()
    authorization.checked_at -= 10  # Arbitrarily slow setup is not token observation age.
    response = request(app)
    assert response.status_code == 200 and response.json() == actor()
    assert authorization.calls >= 1 and f.resolver_calls == 1


def test_commit_aware_service_failure_survives_refresh_task_group(http_boundary):
    f = http_boundary
    authorization = refreshing_authorization(f)
    f.service.failure = CommunicationHttpError("receiver_unavailable", "Observation is unavailable.", status_code=503,
        effect_state="committed", operation_ref="original-operation")
    original = f.service.send

    def slow_send(project, body, *, client_request_id):
        time.sleep(0.12)
        return original(project, body, client_request_id=client_request_id)

    f.service.send = slow_send
    response = post(f)
    assert authorization.calls >= 2
    assert response.status_code == 503 and response.json()["error"]["effect_state"] == "committed"
    assert response.json()["error"]["operation_ref"] == "original-operation" and len(f.service.calls) == 1
