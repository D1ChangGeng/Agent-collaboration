"""Explicit, idempotent adoption of a private installation's owner strategy."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from runtime.domain import DomainAuthority
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.operator_files import read_operator_file
from runtime.surface_config import load_settings


def migrate_owner_records(authority):
    if authority.access_mode != "owner":
        raise ValueError("owner record adoption requires an explicit owner strategy")
    command = CommandEnvelope(command_id="owner-adoption-check", idempotency_key="owner-adoption-check",
        command_type="installation.owner.adopt", correlation_id="installation-upgrade", target_kind="connection",
        target_id=authority.authority_id, expected_revision=0, issued_at=datetime.now(UTC), deadline=None,
        tenant_id=authority.tenant_id, authority_id=authority.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref, grant_ref=authority.context.grant_ref)
    counts = {}
    with authority._connect() as connection, connection.cursor() as cursor:
        authority._authorize(command, cursor)
        identity = (authority.tenant_id, authority.authority_id, authority.context.authority_incarnation)
        cursor.execute("UPDATE grants SET expires_at=NULL,identity_only=TRUE WHERE tenant_id=%s "
                       "AND authority_id=%s AND authority_incarnation=%s AND revoked_at IS NULL", identity)
        counts["identities"] = cursor.rowcount
        cursor.execute("UPDATE enrolled_node_bindings b SET expires_at=NULL FROM enrolled_nodes n "
            "WHERE b.tenant_id=n.tenant_id AND b.node_id=n.node_id AND b.status='active' AND n.status='active' "
            "AND n.tenant_id=%s AND n.authority_id=%s AND n.authority_incarnation=%s", identity)
        counts["node_bindings"] = cursor.rowcount
        cursor.execute("UPDATE enrolled_runtimes r SET expires_at=NULL FROM enrolled_nodes n "
            "WHERE r.tenant_id=n.tenant_id AND r.node_id=n.node_id AND r.status='active' AND n.status='active' "
            "AND r.tenant_id=%s AND r.authority_id=%s AND r.authority_incarnation=%s", identity)
        counts["runtimes"] = cursor.rowcount
        cursor.execute("UPDATE delivery_endpoint_registrations SET expires_at=NULL WHERE status='active' "
            "AND tenant_id=%s AND authority_id=%s AND authority_incarnation=%s", identity)
        counts["signed_endpoints"] = cursor.rowcount
        cursor.execute("UPDATE authority_transport_keys SET expires_at=NULL WHERE status='active' "
            "AND tenant_id=%s AND authority_id=%s AND authority_incarnation=%s", identity)
        counts["authority_keys"] = cursor.rowcount
        cursor.execute("UPDATE deployment_connection_refs SET expires_at=NULL WHERE tenant_id=%s AND status='active'",
                       (authority.tenant_id,))
        counts["connections"] = cursor.rowcount
        cursor.execute("UPDATE delivery_endpoints SET expires_at=NULL WHERE tenant_id=%s AND status='active'",
                       (authority.tenant_id,))
        counts["delivery_endpoints"] = cursor.rowcount
    return counts


def activate_owner_mode(config_path):
    """The caller explicitly chooses one private profile; credentials remain unchanged."""
    config_path = Path(config_path)
    original = read_operator_file(config_path)
    settings = load_settings(config_path)
    context = AuthenticatedContext(**settings.context.model_dump())
    authority = DomainAuthority(settings.dsn_ref.resolve(), context=context,
        authority_binding=(context.authority_id, context.authority_incarnation), access_mode="owner")
    from runtime.auth import LocalCredentialAuthenticator
    LocalCredentialAuthenticator(context).authenticate(settings.credential())
    authority.initialize()
    counts = migrate_owner_records(authority)
    if settings.access_mode != "owner":
        backup = config_path.with_name(config_path.name + ".before-owner-upgrade")
        if not backup.exists():
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(original)
        data = json.loads(original)
        data["access_mode"] = "owner"
        stage = config_path.with_name(config_path.name + ".owner-stage")
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(data, target, indent=2)
            target.write("\n")
        os.replace(stage, config_path)
    return {"access_mode": "owner", "records": counts, "identity_preserved": True}
