"""Actual signature validation with controlled current-authority SQL rows.

These unit doubles do not qualify PostgreSQL locking or a deployed Node.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey
from psycopg.pq import TransactionStatus

from runtime.errors import AcceptanceGuardFailed, RevisionConflict
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_common import digest
from runtime.receiver_crypto import key_fingerprint, public_key, sha256, sign
from runtime.receiver_lifecycle_domain import current_lifecycle_endpoint, original_lifecycle_source
from runtime.receiver_models import EndpointRegistration
from runtime.receiver_recovery_operations import OriginalRecoveryAuthority, RecoveryRequest

NOW = datetime(2026, 11, 7, tzinfo=UTC)


@pytest.fixture
def target():
    state = SimpleNamespace(now=NOW, calls=[])
    node_signer, authority_signer = SigningKey.generate(), SigningKey.generate()
    expiry = NOW + timedelta(hours=1)
    registration = EndpointRegistration(registration_id="registered", endpoint_id="receiver", endpoint_revision=7,
        connection_ref="connection", tenant_id="tenant", authority_id="authority", authority_incarnation="incarnation",
        node_id="node", node_binding_revision=3, runtime_id="runtime", runtime_revision=5,
        machine_id="machine", boot_incarnation="boot", scope_id="scope", agent_slot_id="slot",
        tls_certificate_sha256="a" * 64, config_sha256="b" * 64, expires_at=expiry)
    state.registration = registration
    state.selected = {"tenant_id": "tenant", "endpoint_id": "receiver", "revision": 11, "status": "active",
        "supports_invoke": True, "scope_id": "scope", "agent_slot_id": "slot", "machine_id": "machine",
        "node_id": "node", "boot_incarnation": "boot", "expires_at": expiry}
    state.node_key = {"key_id": "node-key", "tenant_id": "tenant", "node_id": "node", "status": "active",
        "public_key": public_key(node_signer), "fingerprint": key_fingerprint(public_key(node_signer))}
    state.registration_row = registration.model_dump(exclude={"schema_version", "purpose"}) | {
        "registration_json": registration.model_dump(mode="json"), "registration_sha256": sha256(registration),
        "registration_signature": sign(node_signer, registration), "node_key_id": "node-key", "status": "active"}
    state.connection = {"tenant_id": "tenant", "connection_ref": "connection", "revision": 9,
        "locator_host": "127.0.0.1", "locator_port": 8765, "route_class": "loopback", "policy_digest": "c" * 64,
        "expires_at": expiry, "status": "active"}
    state.runtime = {"tenant_id": "tenant", "runtime_id": "runtime", "revision": 5, "node_id": "node",
        "node_binding_revision": 3, "node_boot_incarnation": "boot", "scope_id": "scope", "agent_slot_id": "slot"}
    state.node = {"tenant_id": "tenant", "node_id": "node", "authority_id": "authority",
        "authority_incarnation": "incarnation", "current_binding_revision": 3, "scope_id": "scope", "agent_slot_id": "slot"}
    state.node_binding = {"tenant_id": "tenant", "node_id": "node", "binding_revision": 3,
        "machine_id": "machine", "boot_incarnation": "boot", "key_id": "node-key"}
    state.authority_key = {"tenant_id": "tenant", "authority_id": "authority", "authority_incarnation": "incarnation",
        "key_id": "authority-key", "revision": 4, "public_key": public_key(authority_signer),
        "fingerprint": key_fingerprint(public_key(authority_signer)), "expires_at": expiry}
    state.enrollment_expiry = expiry
    state.registration_rows, state.authority_key_rows = 1, 1
    state.final_wait = timedelta()

    class Cursor:
        connection = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))

        def execute(self, sql, params):
            state.calls.append((sql, params))
            if "FROM delivery_endpoints" in sql:
                self.rows = [(deepcopy(state.selected),)]
            elif "FROM delivery_endpoint_registrations" in sql:
                self.rows = [(deepcopy(state.registration_row), deepcopy(state.connection), deepcopy(state.node_key))] * state.registration_rows
            elif "FROM authority_transport_keys" in sql:
                self.rows = [(deepcopy(state.authority_key),)] * state.authority_key_rows
                state.now += state.final_wait
            else:
                raise AssertionError("unexpected lifecycle SQL")

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    def active_runtime(cursor, runtime):
        assert cursor is state.cursor and runtime == "runtime"
        state.calls.append(("active_runtime", runtime))
        return deepcopy((state.runtime, state.node, state.node_binding, state.node_key, state.enrollment_expiry))

    state.cursor = Cursor()
    state.authority = SimpleNamespace(tenant_id="tenant", access_mode="shared",
        context=SimpleNamespace(authority_id="authority", authority_incarnation="incarnation"),
        enrollment=SimpleNamespace(current_runtime_snapshot=active_runtime), canonical_now=lambda cursor: state.now)
    state.read = lambda: current_lifecycle_endpoint(state.authority, state.cursor, "receiver", 11, journal_generation=2)
    return state


def test_snapshot_keeps_independent_binding_and_transport_versions_in_one_transaction(target):
    value = target.read()
    assert value.binding_epoch == 11 and value.binding.registration.endpoint_revision == 7
    assert value.connection_revision == 9 and value.journal_generation == 2
    assert value.authority_key.revision == 4 and value.valid_until == NOW + timedelta(hours=1)
    assert value.checked_at == NOW and len(value.selection_digest) == 64
    assert all("FOR SHARE" in sql for sql, _params in target.calls if sql != "active_runtime")


@pytest.mark.parametrize("family,field,value", [
    ("selected", "node_id", "replacement-node"), ("selected", "scope_id", "foreign-scope"),
    ("selected", "agent_slot_id", "foreign-slot"), ("selected", "boot_incarnation", "old-boot"),
    ("selected", "supports_invoke", False), ("selected", "status", "revoked"),
    ("registration_row", "runtime_revision", 6), ("registration_row", "config_sha256", "f" * 64),
    ("registration_row", "registration_sha256", "f" * 64), ("registration_row", "node_key_id", "old-key"),
    ("runtime", "node_boot_incarnation", "old-boot"), ("runtime", "revision", 6),
    ("runtime", "node_binding_revision", 4), ("runtime", "agent_slot_id", "other-slot"),
    ("node", "current_binding_revision", 4), ("node", "authority_incarnation", "old-authority"),
    ("node_binding", "key_id", "old-key"), ("node_binding", "machine_id", "other-host"),
    ("node_binding", "boot_incarnation", "old-boot"), ("node_binding", "binding_revision", 4),
    ("node_key", "fingerprint", "f" * 64), ("connection", "connection_ref", "other-connection"),
    ("node_key", "node_id", "other-node"),
    ("connection", "tenant_id", "other-tenant"), ("connection", "revision", 0),
    ("authority_key", "fingerprint", "f" * 64), ("authority_key", "authority_incarnation", "old-authority"),
    ("authority_key", "revision", 0),
])
def test_every_current_identity_axis_is_checked_against_signed_registration(target, family, field, value):
    getattr(target, family)[field] = value
    with pytest.raises((AcceptanceGuardFailed, ValueError)):
        target.read()


def test_operational_epoch_conflict_is_independent_of_registration_revision(target):
    target.selected["revision"] = 12
    with pytest.raises(RevisionConflict):
        target.read()


@pytest.mark.parametrize("family", ["selected", "registration_row", "connection", "authority_key"])
def test_shared_expiry_is_checked_after_later_lock_waits(target, family):
    getattr(target, family)["expires_at"] = NOW + timedelta(seconds=1)
    target.final_wait = timedelta(seconds=2)
    with pytest.raises(AcceptanceGuardFailed):
        target.read()


def test_runtime_enrollment_expiry_is_checked_after_all_lock_waits(target):
    target.enrollment_expiry = NOW + timedelta(seconds=1)
    target.final_wait = timedelta(seconds=2)
    with pytest.raises(AcceptanceGuardFailed):
        target.read()


def test_owner_uses_active_identity_instead_of_automatic_shared_expiry(target):
    target.authority.access_mode = "owner"
    for name in ("selected", "registration_row", "connection", "authority_key"):
        getattr(target, name)["expires_at"] = NOW - timedelta(days=1)
    target.enrollment_expiry = NOW - timedelta(days=1)
    assert target.read().valid_until is None
    target.node_binding["boot_incarnation"] = "replacement-boot"
    with pytest.raises(AcceptanceGuardFailed):
        target.read()


@pytest.mark.parametrize("family", ["registration_rows", "authority_key_rows"])
@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_current_trust_is_not_a_positive_snapshot(target, family, count):
    setattr(target, family, count)
    with pytest.raises(AcceptanceGuardFailed):
        target.read()


def test_node_registration_signature_is_verified_as_actual_bytes(target):
    target.registration_row["registration_signature"] = "0" * 128
    with pytest.raises(ValueError):
        target.read()


def test_standalone_autocommit_is_refused_before_any_query(target):
    target.cursor.connection = SimpleNamespace(autocommit=True, info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    with pytest.raises(AcceptanceGuardFailed):
        target.read()
    assert target.calls == []


def test_explicit_transaction_with_autocommit_connection_is_supported(target):
    target.cursor.connection = SimpleNamespace(autocommit=True, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))
    assert target.read().binding_epoch == 11


@pytest.fixture
def accepted_source():
    context = AuthenticatedContext("tenant", "authority", "incarnation", "original-manager", "original-grant")
    stored = CommandEnvelope(command_id="original-command", command_type="receiver.recovery",
        idempotency_key="original-key", correlation_id="original-command", tenant_id=context.tenant_id,
        authority_id=context.authority_id, authority_incarnation=context.authority_incarnation,
        principal_ref=context.principal_ref, grant_ref=context.grant_ref, target_kind="endpoint", target_id="receiver",
        expected_revision=11, issued_at=NOW - timedelta(minutes=3), deadline=NOW - timedelta(minutes=2))
    admission = stored.model_copy(update={"issued_at": NOW, "deadline": NOW + timedelta(seconds=30)})
    request = RecoveryRequest(action="prepare_receiver", expected_revision=11, reason="Prepare the registered capacity")
    actor = "collaborator:project:manager-slot"
    payload = {"schema_version": "acs-receiver-recovery/1", "project_id": "project", "receiver_id": "receiver",
        "actor": actor, "issuer_context": {"tenant_id": context.tenant_id, "authority_id": context.authority_id,
            "authority_incarnation": context.authority_incarnation, "principal_ref": context.principal_ref,
            "grant_ref": context.grant_ref}, "profile": "root_manager", "request": request.model_dump(mode="json"),
        "command": stored.model_dump(mode="json"), "operation": {"operation_id": "receiver-recovery-original",
            "kind": "recovery", "receiver_ref": "receiver", "binding_epoch": 11, "state": "queued"}}
    state = SimpleNamespace(payload=payload, saved=deepcopy(payload), stored=stored, admission=admission, calls=[],
        command_id=stored.command_id, provider="communication-recovery", workflow="receiver-recovery-original",
        message_id="msg-" + stored.command_id, receipt_operation="receiver-recovery-original",
        input_digest=digest(["receiver", request.model_dump(mode="json")]), authority_checks=0)
    state.authority = SimpleNamespace(context=context, tenant_id=context.tenant_id)

    class Cursor:
        connection = SimpleNamespace(autocommit=False, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))

        def execute(self, sql, params):
            state.calls.append((sql, params))
            if "FROM outbox" in sql:
                self.rows = [(state.message_id, deepcopy(state.saved))]
            elif "FROM operations" in sql:
                self.rows = [(state.command_id, state.provider, state.workflow)]
            elif "FROM collaboration_commands" in sql:
                self.rows = [(state.input_digest, {"operation_id": state.receipt_operation})]
            else:
                raise AssertionError("unexpected source lineage SQL")

        def fetchall(self):
            return self.rows

    def reauthorize(cursor, actual, supplied_request, *, lock_endpoint=True):
        assert cursor is state.cursor and actual is payload and supplied_request == request
        assert lock_endpoint is False
        state.authority_checks += 1
        return OriginalRecoveryAuthority(state.authority, stored, admission, {"revision": 11}, actor)

    state.cursor = Cursor()
    state.recovery = SimpleNamespace(_original_authority=reauthorize, authority=state.authority)
    state.read = lambda: original_lifecycle_source(state.recovery, state.cursor, payload)
    return state


def test_source_uses_original_core_operation_and_keeps_renewed_transport_budget_separate(accepted_source):
    state = accepted_source
    checked, source = state.read()
    assert checked.stored_command == state.stored and checked.admission_command == state.admission
    assert source.operation_ref == "receiver-recovery-original" and source.command_id == "original-command"
    assert source.principal_ref == "original-manager" and source.grant_ref == "original-grant"
    assert source.business_deadline is None and source.command_digest == sha256(state.stored)
    assert state.stored.deadline < NOW < state.admission.deadline
    assert state.payload["command"] == state.stored.model_dump(mode="json") and state.authority_checks == 2
    assert state.calls[2][1][2] == "recovery-actor:" + digest(["incarnation", state.payload["actor"]])
    assert "FROM outbox" in state.calls[0][0] and "FROM operations" in state.calls[1][0]


@pytest.mark.parametrize("field,value", [("command_id", "another-command"), ("provider", "another-provider"),
    ("workflow", "another-operation"), ("message_id", "another-outbox-event"),
    ("input_digest", "0" * 64), ("receipt_operation", "another-operation")])
def test_source_cannot_be_substituted_by_an_unrelated_physical_operation_or_receipt(accepted_source, field, value):
    setattr(accepted_source, field, value)
    with pytest.raises(AcceptanceGuardFailed):
        accepted_source.read()


@pytest.mark.parametrize("field,value", [("project_id", "foreign-project"), ("receiver_id", "another-receiver"),
    ("actor", "another-manager"), ("profile", "engineer"), ("issuer_context", {"principal_ref": "another-manager"}),
    ("command", {}), ("request", {})])
def test_authorized_source_must_match_the_immutable_saved_outbox_fields(accepted_source, field, value):
    accepted_source.saved[field] = value
    with pytest.raises(AcceptanceGuardFailed):
        accepted_source.read()


def test_original_issuer_is_rechecked_after_lineage_row_waits(accepted_source):
    state = accepted_source
    before = state.recovery._original_authority

    def revoke(*args, **kwargs):
        if state.authority_checks:
            raise PermissionError("original issuer revoked during a row wait")
        return before(*args, **kwargs)

    state.recovery._original_authority = revoke
    with pytest.raises(PermissionError):
        state.read()
    assert len(state.calls) == 3
