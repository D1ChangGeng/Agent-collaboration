"""Continuous owner identity preserves target binding and explicit shared governance."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from runtime.auth import LocalCredentialAuthenticator, LocalCredentialUnavailable
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope


def command(context, **changes):
    values = {"command_id": "owner-request", "command_type": "work_item.read",
        "idempotency_key": "owner-request", "correlation_id": "owner-request",
        "tenant_id": context.tenant_id, "authority_id": context.authority_id,
        "authority_incarnation": context.authority_incarnation, "principal_ref": context.principal_ref,
        "grant_ref": context.grant_ref, "target_kind": "work_item", "target_id": "work",
        "expected_revision": 0, "issued_at": datetime.now(UTC)-timedelta(days=30)}
    values.update(changes)
    return CommandEnvelope(**values)


def cursor(*answers):
    value = Mock()
    value.fetchone.side_effect = list(answers)
    return value


def test_owner_has_no_short_lived_permission_chain():
    authority = DomainAuthority("fixture-only", access_mode="owner")
    current = command(authority.context)
    db = cursor((1,), (1,))
    db.fetchall.return_value = [(authority.context.grant_ref, None)]
    authority._authorize(current, db, "runtime.invoke", "project-scope")
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert not any("expires_at" in item or "g.permissions" in item or "grant_delegations" in item for item in statements)
    assert current.deadline is None


@pytest.mark.parametrize("field", ["tenant_id", "authority_id", "authority_incarnation", "principal_ref", "grant_ref"])
def test_owner_request_cannot_replace_authenticated_context(field):
    authority = DomainAuthority("fixture-only", access_mode="owner")
    with pytest.raises(AuthorizationDenied):
        authority._authorize(command(authority.context, **{field:"other"}), cursor(), "runtime.invoke")


def test_owner_cannot_address_missing_scope_or_inactive_authority():
    authority = DomainAuthority("fixture-only", access_mode="owner")
    with pytest.raises(AuthorizationDenied):
        authority._authorize(command(authority.context), cursor(None), "runtime.invoke")
    with pytest.raises(AuthorizationDenied):
        authority._authorize(command(authority.context), cursor((1,), None), "runtime.invoke", "missing")


def test_shared_deployment_still_requires_expiring_authorization():
    authority = DomainAuthority("fixture-only", access_mode="shared")
    authority.canonical_now = Mock(return_value=datetime.now(UTC))
    with pytest.raises(AuthorizationDenied):
        authority._authorize(command(authority.context), cursor(), "runtime.invoke")


def test_transport_credential_is_still_required():
    import hashlib
    authority = DomainAuthority("fixture-only", access_mode="owner")
    context = replace(authority.context, credential_hash=hashlib.sha256(b"owner-secret").hexdigest())
    authenticator = LocalCredentialAuthenticator(context)
    assert authenticator.authenticate("owner-secret") == context
    with pytest.raises(LocalCredentialUnavailable):
        authenticator.authenticate("other")


def test_owner_explicit_identity_revocation_still_stops_operations():
    authority = DomainAuthority("fixture-only", access_mode="owner")
    db = cursor((1,))
    db.fetchall.return_value = [(authority.context.grant_ref, datetime.now(UTC))]
    with pytest.raises(AuthorizationDenied):
        authority._authorize(command(authority.context), db, "runtime.invoke")
