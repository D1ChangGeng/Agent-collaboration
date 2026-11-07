"""Recovery control-flow fences with synthetic stores/providers; no DB qualification."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.client_contracts import ClientContracts
from runtime.errors import AuthorizationDenied, RevisionConflict
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_http import OAuthScopeDenied
from runtime.receiver_recovery_operations import ReceiverRecoveryOperations, RecoveryRequest

NOW = datetime(2026, 11, 6, tzinfo=UTC)
TOKEN = "synthetic-credential"
ENDPOINT = {"revision": 1, "status": "active", "scope_id": "synthetic-scope", "agent_slot_id": "synthetic-slot",
            "machine_id": "synthetic-machine", "node_id": "synthetic-node", "boot_incarnation": "synthetic-boot"}


class FixtureCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture
def recovery_boundary():
    state = SimpleNamespace(endpoint=deepcopy(ENDPOINT), authorized=True, auth_calls=0, calls=[], saves=[], transactions=0)

    def authenticate(credential):
        state.auth_calls += 1
        if not state.authorized or credential != TOKEN:
            raise PermissionError("synthetic expired credential")

    def inspect():
        state.calls.append("inspect")
        return {"state": "idle"}

    def forbidden_legacy_callback(*_args):
        pytest.fail("an unfenced lifecycle callback was entered")

    state.provider = SimpleNamespace(descriptor=lambda: deepcopy(ENDPOINT), inspect_runtime=inspect,
        prepare_runtime=forbidden_legacy_callback, resume_runtime=forbidden_legacy_callback,
        rebind_runtime=forbidden_legacy_callback)
    authority = SimpleNamespace(tenant_id="synthetic-tenant", _delivery_endpoints={"synthetic-receiver": state.provider})

    @contextmanager
    def transaction():
        state.transactions += 1
        yield authority, SimpleNamespace(cursor=FixtureCursor)

    authority.transaction = transaction
    projects = SimpleNamespace(service=SimpleNamespace(authority=authority, authenticate=authenticate))
    recovery = ReceiverRecoveryOperations(projects)
    state.payload = {"project_id": "synthetic-project", "receiver_id": "synthetic-receiver", "actor": "synthetic-actor",
        "request": {"action": "inspect", "expected_revision": 1, "reason": "Controlled fence test"},
        "operation": {"operation_id": "receiver-recovery-synthetic", "kind": "recovery", "state": "queued",
            "message_handle": None, "receiver_ref": "synthetic-receiver", "binding_epoch": 1, "effect_state": "committed",
            "reason_code": None, "evidence_refs": ["command:synthetic"], "revision": 1,
            "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}}
    recovery._row = lambda *_args, **_kwargs: deepcopy(state.payload)
    recovery._authorize = lambda *_args: (SimpleNamespace(canonical_now=lambda _cursor: NOW),
        None, deepcopy(state.endpoint), "synthetic-actor", None)
    recovery._original_authority = lambda *_args: None

    def save(_cursor, _payload, operation, *, done=False):
        ClientContracts().validate("Operation", operation)
        state.saves.append((deepcopy(operation), done))
        state.payload["operation"] = deepcopy(operation)

    recovery._save = save
    state.recovery, state.projects = recovery, projects
    state.advance = lambda: recovery.advance("synthetic-project", "receiver-recovery-synthetic", TOKEN)
    return state


@pytest.mark.parametrize("action", ["prepare_receiver", "resume_receiver", "rebind_receiver"])
def test_legacy_lifecycle_presence_or_native_readback_cannot_establish_a_fence(recovery_boundary, action):
    f = recovery_boundary
    f.payload["request"]["action"] = action
    if action == "rebind_receiver":
        f.payload["request"]["target_endpoint_ref"] = "another-endpoint"
    operation = f.advance()
    assert operation["state"] == "definitively_rejected" and operation["effect_state"] == "committed"
    assert operation["reason_code"] == action + "_fenced_lifecycle_unsupported"
    assert f.calls == [] and len(f.saves) == 1 and f.saves[0][1] is True
    assert f.advance() == operation and len(f.saves) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_inspection_does_not_contact_provider_without_matching_receiver_identity(recovery_boundary, missing):
    f = recovery_boundary
    f.provider.descriptor = None if missing else lambda: {**ENDPOINT, "boot_incarnation": "replacement-boot"}
    operation = f.advance()
    assert operation["state"] == "unknown" and operation["reason_code"] == "receiver_binding_unconfirmed"
    assert operation["effect_state"] == "committed" and f.calls == []


def test_provider_identity_change_during_readback_does_not_become_receiver_state(recovery_boundary):
    f = recovery_boundary

    def inspect():
        f.calls.append("inspect")
        f.provider.descriptor = lambda: {**ENDPOINT, "node_id": "replacement-node"}
        return {"state": "idle"}

    f.provider.inspect_runtime = inspect
    operation = f.advance()
    assert operation["state"] == "unknown" and operation["effect_state"] == "committed"
    assert operation["reason_code"] == "receiver_binding_changed_during_observation"


def test_provider_state_is_normalized_instead_of_echoing_arbitrary_private_text(recovery_boundary):
    f = recovery_boundary
    f.provider.inspect_runtime = lambda: {"state": "private-session-details"}
    operation = f.advance()
    assert operation["reason_code"] == "receiver_unknown" and "private-session-details" not in str(operation)


def test_revoked_transport_cannot_return_post_call_result_and_marker_survives(recovery_boundary):
    f = recovery_boundary

    def inspect():
        f.calls.append("inspect")
        f.authorized = False
        return {"state": "idle"}

    f.provider.inspect_runtime = inspect
    with pytest.raises(PermissionError):
        f.advance()
    assert f.auth_calls == 3 and f.calls == ["inspect"]
    assert f.payload["operation"]["state"] == "preparing"
    assert f.payload["operation"]["effect_state"] == "committed"
    f.authorized = True
    assert f.advance() == f.payload["operation"] and f.calls == ["inspect"]


@pytest.mark.parametrize("delivery_state", ["uncertain", "delivered", "blocked"])
def test_declined_retry_preserves_committed_audit_without_claiming_new_native_effect(recovery_boundary, monkeypatch, delivery_state):
    from runtime.communication_delivery_observer import CommunicationDeliveryObserver
    from runtime.delivery import DeliveryDispatcher

    f = recovery_boundary
    f.payload["request"] |= {"action": "retry_delivery", "operation_ref": "original-delivery"}
    monkeypatch.setattr(CommunicationDeliveryObserver, "observe", lambda *_args, **_kwargs: {"delivery_state": delivery_state})
    monkeypatch.setattr(DeliveryDispatcher, "dispatch", lambda *_args: pytest.fail("a declined retry dispatched Native input"))
    operation = f.advance()
    assert operation["state"] == ("definitively_rejected" if delivery_state == "uncertain" else "completed")
    assert operation["effect_state"] == "committed"


def test_ambiguous_dispatch_retains_possible_effect_and_is_never_reentered(recovery_boundary, monkeypatch):
    from runtime.communication_delivery_observer import CommunicationDeliveryObserver
    from runtime.delivery import DeliveryDispatcher

    f = recovery_boundary
    f.payload["request"] |= {"action": "retry_delivery", "operation_ref": "original-delivery"}
    monkeypatch.setattr(CommunicationDeliveryObserver, "observe", lambda *_args, **_kwargs:
        {"delivery_state": "queued", "message_handle": "message:synthetic-project:original-message"})

    def dispatch(_self, identity):
        assert identity["operation_id"] == "original-delivery"
        f.calls.append("dispatch")
        raise OSError("synthetic uncertain Native outcome")

    monkeypatch.setattr(DeliveryDispatcher, "dispatch", dispatch)
    operation = f.advance()
    assert operation["state"] == "unknown" and operation["effect_state"] == "native_possible"
    assert f.advance() == operation and f.calls == ["dispatch"]


def test_nonqueued_operation_is_observed_consistently_without_fabricated_terminal_result(recovery_boundary):
    f = recovery_boundary
    f.payload["operation"] |= {"state": "submitting", "effect_state": "native_possible", "revision": 2}
    assert f.advance() == f.payload["operation"] and f.saves == [] and f.calls == []


@pytest.mark.parametrize("changed", [False, True])
def test_receiver_cas_freezes_authorized_selection_in_domain_lock_order(changed):
    events = []
    current = {**ENDPOINT, "revision": 2} if changed else deepcopy(ENDPOINT)
    rows = iter([(deepcopy(ENDPOINT),), (current,)])
    cursor = SimpleNamespace(execute=lambda query, _params: events.append(query), fetchone=lambda: next(rows))

    def authorize(*_args):
        events.append("authorized-grant-and-scope")
        return SimpleNamespace(), ("synthetic-scope",), None

    projects = SimpleNamespace(service=SimpleNamespace(authority=SimpleNamespace()),
        context=SimpleNamespace(tenant_id="synthetic-tenant"), _authorize=authorize,
        _check_tool_policy=lambda _name: None,
        _visible_scopes=lambda *_args: None, _communication_address=lambda *_args: "synthetic-actor")
    recovery = ReceiverRecoveryOperations(projects)
    args = (cursor, projects.service.authority, "synthetic-project", "synthetic-receiver",
            RecoveryRequest(action="inspect", expected_revision=1, reason="Controlled CAS"))
    if changed:
        with pytest.raises(RevisionConflict):
            recovery._authorize(*args)
    else:
        assert recovery._authorize(*args)[2] == ENDPOINT
    assert "FOR SHARE" not in events[0]
    assert events[1] == "authorized-grant-and-scope" and events[-1].endswith("FOR SHARE")


def test_profile_denial_precedes_even_receiver_metadata_lookup():
    from runtime.errors import AuthorizationDenied

    def denied(_name):
        raise AuthorizationDenied("synthetic-principal", "synthetic-grant")

    authority = SimpleNamespace()
    projects = SimpleNamespace(service=SimpleNamespace(authority=authority), _check_tool_policy=denied)
    recovery = ReceiverRecoveryOperations(projects)
    cursor = SimpleNamespace(execute=lambda *_args: pytest.fail("denied Profile queried receiver metadata"))
    with pytest.raises(AuthorizationDenied):
        recovery._authorize(cursor, authority, "synthetic-project", "synthetic-receiver",
            RecoveryRequest(action="inspect", expected_revision=1, reason="Explicit denied request"))


def test_original_issuer_recheck_refreshes_auth_budget_without_replacing_grant_or_stored_command(monkeypatch):
    import runtime.project_service as project_module

    context = AuthenticatedContext("synthetic-tenant", "synthetic-authority", "synthetic-incarnation",
                                   "synthetic-principal", "original-grant")
    old = CommandEnvelope(command_id="original-command", command_type="receiver.recovery", idempotency_key="original-key",
        correlation_id="original-command", tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref, grant_ref=context.grant_ref,
        target_kind="endpoint", target_id="synthetic-receiver", expected_revision=1,
        issued_at=NOW - timedelta(minutes=5), deadline=NOW - timedelta(minutes=4))
    fresh = old.model_copy(update={"command_id": "observation-command", "issued_at": NOW, "deadline": NOW + timedelta(seconds=30)})
    checked = []
    bound = SimpleNamespace(_authorize=lambda command, _cursor, _permission: checked.append(command))
    monkeypatch.setattr(ReceiverRecoveryOperations, "_authorize", lambda *_args:
        (bound, fresh, deepcopy(ENDPOINT), "synthetic-actor", None))
    monkeypatch.setattr(project_module, "ProjectService", lambda service, catalog, profile:
        SimpleNamespace(service=service, catalog=catalog, profile=profile))
    authority = SimpleNamespace(context=context, _delivery_endpoints={})
    recovery = ReceiverRecoveryOperations(SimpleNamespace(service=SimpleNamespace(authority=authority), catalog={}, profile="root_manager"))
    payload = {"issuer_context": {"tenant_id": context.tenant_id, "authority_id": context.authority_id,
        "authority_incarnation": context.authority_incarnation, "principal_ref": context.principal_ref, "grant_ref": context.grant_ref},
        "profile": "root_manager", "project_id": "synthetic-project", "receiver_id": "synthetic-receiver",
        "actor": "synthetic-actor", "command": old.model_dump(mode="json")}
    stored = deepcopy(payload["command"])
    recovery._original_authority(None, payload, RecoveryRequest(action="inspect", expected_revision=1, reason="Controlled recheck"))
    assert len(checked) == 1 and checked[0].command_id == old.command_id and checked[0].grant_ref == "original-grant"
    assert checked[0].issued_at == NOW and checked[0].deadline == fresh.deadline
    assert payload["command"] == stored


@pytest.mark.parametrize("action", ["prepare_receiver", "resume_receiver"])
@pytest.mark.parametrize("allowed", [False, True])
def test_oauth_recovery_scope_narrows_the_existing_runtime_invoke_grant(action, allowed):
    permissions, token_checks = [], []
    cursor = SimpleNamespace(execute=lambda *_args: None, fetchone=lambda: (deepcopy(ENDPOINT),))
    bound = SimpleNamespace(_authorize=lambda _command, _cursor, permission, _scope: permissions.append(permission))

    def authorize_permissions(required):
        token_checks.append(tuple(required))
        if not allowed:
            raise OAuthScopeDenied("OAuth runtime.invoke scope is unavailable")

    projects = SimpleNamespace(service=SimpleNamespace(authority=SimpleNamespace()),
        context=SimpleNamespace(tenant_id="synthetic-tenant", principal_ref="actor", grant_ref="grant"),
        token_authorization=SimpleNamespace(authorize_permissions=authorize_permissions),
        _check_tool_policy=lambda _name: None,
        _authorize=lambda *_args: (bound, ("synthetic-root",), object()),
        _visible_scopes=lambda *_args: None, _communication_address=lambda *_args: "synthetic-actor")
    recovery = ReceiverRecoveryOperations(projects)
    request = RecoveryRequest(action=action, expected_revision=1, reason="Explicit bounded recovery")
    if allowed:
        result = recovery._authorize(cursor, object(), "synthetic-project", "synthetic-receiver", request)
        assert result[3] == "synthetic-actor"
    else:
        with pytest.raises(AuthorizationDenied):
            recovery._authorize(cursor, object(), "synthetic-project", "synthetic-receiver", request)
    assert token_checks == [("runtime.invoke",)]
    assert permissions == ["collaborators.manage", "grants.manage", *(["runtime.invoke"] if allowed else [])]
