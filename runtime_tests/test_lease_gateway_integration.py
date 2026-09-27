"""Real PostgreSQL LeaseAuthority + real Linux files; no mocked authorization.

The adjacent Lease suite supplies an isolated-schema DomainAuthority fixture.
Only filesystem crash locations are injected. These cases exercise integration,
not overall Runtime/Driver or cross-machine Gate completion.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import replace

import pytest

from runtime.domain import DomainAuthority
from runtime.effects import LocalFileEffectGateway
from runtime.errors import EffectUnavailable, FencingRejected
from runtime.lease_authority import LeaseAuthority
from runtime_tests import test_lease_authority as lease_suite
from runtime_tests.enrollment_fixture import register_execution_fixture
from runtime_tests.test_lease_authority import (
    PERMISSIONS,
    acquire,
    command,
    execute,
    fence_args,
    history_args,
    lifecycle,
    reader,
    request,
    wait_past_expiry,
)

authority = lease_suite.authority

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="requires real Linux filesystem backend"
)


def gateway(domain, root):
    assert isinstance(domain.leases, LeaseAuthority)
    return LocalFileEffectGateway(
        domain.leases,
        root,
        scope_id="local-scope",
        resource_paths={"resource-1": "output.txt"},
    )


@pytest.mark.parametrize("terminal", ["released", "expired"])
def test_real_history_reads_after_lease_termination(authority, tmp_path, terminal):
    lease, _, _ = acquire(authority, ttl=5 if terminal == "expired" else 300)
    payload = b"real grant, real file, durable original operation"
    root = tmp_path / "effects"
    with gateway(authority, root) as writer:
        result = writer.write(
            **fence_args(authority, lease),
            relative_path="output.txt",
            payload=payload,
            operation_id="integration-original",
        )
        assert result["sha256"] == hashlib.sha256(payload).hexdigest()
        if terminal == "released":
            lifecycle(authority, lease, "release")
        else:
            wait_past_expiry(lease)
            assert authority.leases.expire_leases() == 1
        status = execute(
            authority, "SELECT status FROM leases WHERE lease_id=%s", (lease["lease_id"],)
        )
        assert status == [(terminal,)]
        with pytest.raises(FencingRejected):
            writer.readback(
                **fence_args(authority, lease),
                readback_ref="output.txt",
                expected_operation_id="integration-original",
            )
        read_domain = reader(authority, ("effect.read",))
        with gateway(read_domain, root) as observer:
            observed = observer.historical_readback(
                **history_args(read_domain, lease),
                readback_ref="output.txt",
                expected_operation_id="integration-original",
            )
        assert observed["status"] == "verified"
        assert observed["sha256"] == result["sha256"]
        assert (root / "output.txt").read_bytes() == payload


def test_real_authority_rollover_reader_preserves_old_intent(authority, tmp_path):
    lease, _, _ = acquire(authority)
    root = tmp_path / "effects"
    operation = "integration-before-rollover"
    with gateway(authority, root) as writer:
        writer.write(
            **fence_args(authority, lease),
            relative_path="output.txt",
            payload=b"old incarnation result",
            operation_id=operation,
        )
        execute(
            authority,
            "UPDATE authority_instances SET status='revoked' "
            "WHERE authority_id=%s AND authority_incarnation=%s",
            (authority.context.authority_id, authority.context.authority_incarnation),
        )
        new_context = replace(
            authority.context,
            authority_incarnation="rollover-" + uuid.uuid4().hex,
            principal_ref="rollover-reader",
            grant_ref="grant:rollover-reader",
        )
        execute(
            authority,
            "INSERT INTO authority_instances(authority_id,authority_incarnation,status) "
            "VALUES (%s,%s,'active')",
            (new_context.authority_id, new_context.authority_incarnation),
        )
        assert execute(
            authority,
            "SELECT authority_incarnation FROM authority_instances "
            "WHERE authority_id=%s AND status='active'",
            (new_context.authority_id,),
        ) == [(new_context.authority_incarnation,)]
        read_domain = DomainAuthority(authority._dsn, new_context)
        read_domain.bootstrap_local_grant(("effect.read",))
        with pytest.raises(FencingRejected):
            writer.write(
                **fence_args(authority, lease),
                relative_path="output.txt",
                payload=b"old incarnation result",
                operation_id=operation,
            )
        with gateway(read_domain, root) as observer:
            observed = observer.historical_readback(
                **history_args(read_domain, lease),
                readback_ref="output.txt",
                expected_operation_id=operation,
            )
        assert observed["status"] == "verified"
        key = hashlib.sha256(operation.encode()).hexdigest()
        intent = json.loads(
            (root / writer.MARKER_DIR / "operations" / (key + ".intent")).read_text()
        )["body"]
        assert intent["owner"]["authority_incarnation"] == authority.context.authority_incarnation
        assert intent["owner"]["authority_incarnation"] != read_domain.context.authority_incarnation
        assert intent["lease_id"] == lease["lease_id"]


def test_real_prepared_operation_resumes_with_new_lease_and_records_executor(
    authority, tmp_path, monkeypatch
):
    original_lease, _, _ = acquire(authority)
    root = tmp_path / "effects"
    operation = "integration-resume"
    real_replace = os.replace
    inject_crash = True
    actual_replacements = []

    def fail_before_resource_replace(source, destination, **kwargs):
        nonlocal inject_crash
        if destination == "output.txt":
            if inject_crash:
                inject_crash = False
                raise OSError("injected crash after durable intent, before resource replacement")
            actual_replacements.append(destination)
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", fail_before_resource_replace)
    with gateway(authority, root) as writer:
        with pytest.raises(EffectUnavailable, match="injected crash"):
            writer.write(
                **fence_args(authority, original_lease),
                relative_path="output.txt",
                payload=b"resumed real effect",
                operation_id=operation,
            )
        assert not (root / "output.txt").exists()
        lifecycle(authority, original_lease, "release")
        replacement = DomainAuthority(
            authority._dsn,
            replace(
                authority.context, principal_ref="recovery-producer", grant_ref="grant:recovery"
            ),
        )
        replacement.bootstrap_local_grant(PERMISSIONS)
        register_execution_fixture(replacement, work_item_id="w-1", runtime_id="runtime-2", attempt_id="a-2")
        new_lease = replacement.leases.acquire_lease(
            command(replacement),
            request(replacement, owner_attempt_id="a-2", owner_runtime_id="runtime-2"),
        )
        assert new_lease["generation"] == original_lease["generation"] + 1
        with pytest.raises(FencingRejected):
            writer.resume(
                **fence_args(authority, original_lease),
                relative_path="output.txt",
                operation_id=operation,
            )
        kwargs = fence_args(replacement, new_lease)
        kwargs.update(attempt_id="a-2", runtime_id="runtime-2")
        with gateway(replacement, root) as recovery:
            result = recovery.resume(**kwargs, relative_path="output.txt", operation_id=operation)
            assert (
                recovery.resume(**kwargs, relative_path="output.txt", operation_id=operation)
                == result
            )
        assert actual_replacements == ["output.txt"]
        assert (root / "output.txt").read_bytes() == b"resumed real effect"
        key = hashlib.sha256(operation.encode()).hexdigest()
        records = root / writer.MARKER_DIR / "operations"
        intent = json.loads((records / (key + ".intent")).read_text())["body"]
        completion = json.loads((records / (key + ".completed")).read_text())["body"]
        assert intent["lease_id"] == original_lease["lease_id"]
        assert intent["principal_ref"] == authority.context.principal_ref
        assert completion["completed_by"]["lease_id"] == new_lease["lease_id"]
        assert completion["completed_by"]["principal_ref"] == replacement.context.principal_ref
        assert completion["completed_by"]["owner"]["grant_ref"] == replacement.context.grant_ref
        assert completion["completed_by"]["owner"]["attempt_id"] == "a-2"
        assert completion["completion_basis"] == "applied_now"


def test_real_outer_transaction_readback_reuses_authorization_and_seals_marker_bytes(
    authority, tmp_path
):
    lease, _, _ = acquire(authority)
    root = tmp_path / "effects"
    operation = "integration-shared-transaction"
    payload = b"bytes observed inside the acceptance transaction"
    with gateway(authority, root) as writer:
        writer.write(
            **fence_args(authority, lease),
            relative_path="output.txt",
            payload=payload,
            operation_id=operation,
        )
        lifecycle(authority, lease, "release")
        read_domain = reader(authority, ("effect.read",))
        with (
            gateway(read_domain, root) as observer,
            read_domain._connect() as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SET LOCAL lock_timeout='500ms'")
            cursor.execute(
                "SELECT work_item_id FROM work_items WHERE tenant_id=%s AND work_item_id='w-1' FOR UPDATE",
                (read_domain.tenant_id,),
            )
            assert cursor.fetchone() == ("w-1",)
            # Same outer locks held by Domain acceptance, on real DB rows.
            read_domain._authorize(
                read_domain.leases._read_command("resource-1", "effect.read"),
                cursor,
                "effect.read",
                "local-scope",
            )
            cursor.execute(
                "SELECT lease_id FROM leases WHERE tenant_id=%s AND lease_id=%s FOR UPDATE",
                (read_domain.tenant_id, lease["lease_id"]),
            )
            assert cursor.fetchone() == (lease["lease_id"],)
            observed = observer.historical_readback_in_transaction(
                cursor,
                **history_args(read_domain, lease),
                readback_ref="output.txt",
                expected_operation_id=operation,
            )
            assert observed["status"] == "verified"
            assert observed["completion_state"] == "completed"
            assert observed["operation_id"] == operation
            assert observed["sha256"] == hashlib.sha256(payload).hexdigest()
            assert observed["size_bytes"] == observed["bytes"] == len(payload)
            key = hashlib.sha256(operation.encode()).hexdigest()
            records = root / writer.MARKER_DIR / "operations"
            for suffix, field in (
                (".intent", "intent_sha256"),
                (".completed", "completion_sha256"),
            ):
                envelope = json.loads((records / (key + suffix)).read_bytes())
                canonical = json.dumps(
                    envelope["body"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode()
                assert (
                    observed[field] == envelope["sha256"] == hashlib.sha256(canonical).hexdigest()
                )
            # The same transaction sees its own revocation. Shared cursor
            # must still authorize, even though all required locks exist.
            cursor.execute(
                "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
                (read_domain.context.grant_ref,),
            )
            with pytest.raises(FencingRejected):
                observer.historical_readback_in_transaction(
                    cursor,
                    **history_args(read_domain, lease),
                    readback_ref="output.txt",
                    expected_operation_id=operation,
                )
        assert (root / "output.txt").read_bytes() == payload
