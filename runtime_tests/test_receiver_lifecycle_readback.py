"""Original-scope read authorization with real immutable signed model values.

Project policy and cursor rows are controlled E1 ports; no PG/Host is contacted.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_contract import LifecycleSource, sign_permit
from runtime.receiver_lifecycle_readback import require_original_lifecycle_read
from runtime_tests.test_receiver_lifecycle_contract import AUTHORITY_KEY, NOW, context


@pytest.fixture
def history(monkeypatch):
    import runtime.project_service as project_module

    c = context()
    command = CommandEnvelope(command_id=c.source.command_id, command_type="receiver.recovery",
        idempotency_key=c.source.command_id, correlation_id=c.source.command_id,
        tenant_id=c.source.tenant_id, authority_id=c.source.authority_id,
        authority_incarnation=c.source.authority_incarnation, principal_ref=c.source.principal_ref,
        grant_ref=c.source.grant_ref, target_kind="endpoint", target_id=c.target.registration.endpoint_id,
        expected_revision=c.target.binding_epoch, issued_at=NOW - timedelta(minutes=3), deadline=NOW - timedelta(minutes=2))
    issuer = {"tenant_id": c.source.tenant_id, "authority_id": c.source.authority_id,
        "authority_incarnation": c.source.authority_incarnation, "principal_ref": c.source.principal_ref,
        "grant_ref": c.source.grant_ref}
    request = {"action": "prepare_receiver", "expected_revision": c.target.binding_epoch, "reason": "Original prepare",
        "operation_ref": None, "target_endpoint_ref": None}
    source = LifecycleSource(**(c.source.model_dump() | {"command_digest": sha256(command),
        "issuer_context_digest": sha256(issuer), "request_digest": sha256(request)}))
    plan = c.plan.model_copy(update={"source": source})
    from runtime.receiver_lifecycle_contract import lifecycle_plan_digest

    permit = c.permit.model_copy(update={"plan": plan, "semantic_digest": lifecycle_plan_digest(plan)})
    signed = sign_permit(permit, AUTHORITY_KEY)
    payload = {"project_id": source.project_id, "receiver_id": c.target.registration.endpoint_id,
        "actor": source.actor_address, "issuer_context": issuer, "profile": source.profile,
        "command": command.model_dump(mode="json"), "request": request,
        "operation": {"operation_id": source.operation_ref, "receiver_ref": c.target.registration.endpoint_id,
            "binding_epoch": c.target.binding_epoch, "state": "unknown", "effect_state": "native_possible"},
        "lifecycle": {"permit": signed.model_dump(mode="json"), "permit_digest": sha256(permit),
            "first_plan_digest": lifecycle_plan_digest(plan)}}
    state = SimpleNamespace(payload=payload, signed=signed, source=source, calls=[], allowed=True,
        actor=source.actor_address, scopes=[c.target.registration.scope_id], revoke_after_wait=False)
    authority = SimpleNamespace(context=SimpleNamespace(principal_ref="node-observer", grant_ref="node-observer-grant"),
                                _delivery_endpoints={})
    state.recovery = SimpleNamespace(authority=authority, projects=SimpleNamespace(catalog={}),
        _row=lambda _cursor, _project, _operation, lock: deepcopy(state.payload))

    class Projects:
        def __init__(self, _shared, _catalog, *, profile):
            assert profile == source.profile

        def _check_tool_policy(self, name):
            assert name == "list_harnesses"
            if not state.allowed:
                raise AuthorizationDenied(source.principal_ref, source.grant_ref)

        def _authorize(self, _authority, _cursor, project, name, args):
            state.calls.append((name, project, args))
            return _authority, ("root-scope",), object()

        def _visible_scopes(self, *_args):
            return state.scopes

        def _communication_address(self, *_args):
            return state.actor

    monkeypatch.setattr(project_module, "ProjectService", Projects)

    class Cursor:
        def execute(self, sql, params):
            assert "FROM operations" in sql and "delivery_endpoints" not in sql
            state.calls.append((sql, params))
            if state.revoke_after_wait:
                state.allowed = False

        def fetchone(self):
            return source.command_id, "communication-recovery", source.operation_ref

    state.cursor = Cursor()
    state.read = lambda: require_original_lifecycle_read(state.recovery, state.cursor, state.signed)
    return state


def test_expired_mutation_budget_does_not_hide_original_fact_with_current_original_scope_authority(history):
    source = history.read()
    assert source == history.source
    args = history.calls[0][2]
    assert args["scope_handle"].endswith(history.signed.permit.plan.target.registration.scope_id)
    assert len(history.calls) == 3


@pytest.mark.parametrize("defect", ["actor", "scope", "role", "permit", "context", "command"])
def test_original_fact_requires_current_original_actor_scope_and_immutable_subject(history, defect):
    if defect == "actor":
        history.actor = "another-manager"
    elif defect == "scope":
        history.scopes = ["only-new-replacement-scope"]
    elif defect == "role":
        history.allowed = False
    elif defect == "permit":
        history.payload["lifecycle"]["permit_digest"] = "0" * 64
    elif defect == "context":
        history.payload["issuer_context"]["trusted_client"] = True
    else:
        history.payload["command"]["principal_ref"] = "another-manager"
    with pytest.raises(AuthorizationDenied):
        history.read()


def test_original_read_grant_is_rechecked_after_physical_row_wait(history):
    history.revoke_after_wait = True
    with pytest.raises(AuthorizationDenied):
        history.read()
