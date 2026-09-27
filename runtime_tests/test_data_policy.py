from __future__ import annotations

import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.artifacts import LocalArtifactStore
from runtime.data_policy import DomainBoundArtifactStore
from runtime.domain import DomainAuthority
from runtime.errors import AuthorizationDenied
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.source import SourceAuthorizationError, SourceService
from runtime.source_models import SourceRequest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True,
    ).stdout.strip()


def _command(authority: DomainAuthority, command_type: str, *, target: str) -> CommandEnvelope:
    now = datetime.now(UTC)
    return CommandEnvelope(
        command_id=f"data-policy-{uuid.uuid4().hex}",
        command_type=command_type,
        idempotency_key=f"data-policy-key-{uuid.uuid4().hex}",
        correlation_id="p2-opencode-data-policy",
        tenant_id=authority.tenant_id,
        authority_id=authority.authority_id,
        authority_incarnation=authority.context.authority_incarnation,
        principal_ref=authority.context.principal_ref,
        grant_ref=authority.context.grant_ref,
        target_kind="work_item",
        target_id=target,
        expected_revision=0,
        issued_at=now - timedelta(seconds=1),
        deadline=now + timedelta(minutes=5),
        payload={"scope_id": "local-scope"},
    )


@pytest.fixture
def authority_and_dsn():
    base = os.environ.get("ACS_P1_DSN")
    if not base:
        pytest.skip("ACS_P1_DSN is not configured; real data-policy boundary is NOT_RUN")
    schema = "data_policy_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-csearch_path={schema} -cstatement_timeout=15000")
    try:
        yield dsn
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_domain_bound_artifact_read_is_revoked_at_cas_boundary(authority_and_dsn, tmp_path):
    authority = DomainAuthority(
        authority_and_dsn,
        context=AuthenticatedContext(
            "data-policy-tenant", "acs-p1-authority", "local-1",
            "agent:data-policy", "grant:data-policy",
        ),
    )
    authority.initialize()
    authority.bootstrap_local_grant(("artifact.read", "artifact.write", "source.read"))
    raw_store = LocalArtifactStore(tmp_path / "cas", "local-scope")
    command = _command(authority, "artifact.read", target="data-policy")
    bound = DomainBoundArtifactStore(raw_store, authority, command)
    ref = bound.put_bytes(b"protected artifact", kind="readback")
    assert bound.read(ref) == b"protected artifact"
    with authority._connect() as connection:
        connection.execute(
            "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
            (authority.context.grant_ref,),
        )
    with pytest.raises(AuthorizationDenied):
        bound.read(ref)
    assert raw_store.read(ref) == b"protected artifact"
    bound.close()


def test_source_service_domain_callbacks_reject_after_grant_revocation(authority_and_dsn, tmp_path):
    authority = DomainAuthority(
        authority_and_dsn,
        context=AuthenticatedContext(
            "source-policy-tenant", "acs-p1-authority", "local-1",
            "agent:source-policy", "grant:source-policy",
        ),
    )
    authority.initialize()
    authority.bootstrap_local_grant(("artifact.read", "artifact.write", "source.read"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "source-policy@example.invalid")
    _git(repo, "config", "user.name", "Source Policy")
    (repo / "README.md").write_text("source policy\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "source-policy")
    store = LocalArtifactStore(tmp_path / "cas", "local-scope")
    service = SourceService(store, authorized_roots=[tmp_path])
    request = SourceRequest(
        root=repo, tenant_id=authority.tenant_id, scope_id="local-scope",
        root_id="root", route_id="route", expected_commit=_git(repo, "rev-parse", "HEAD"),
        expected_tree=_git(repo, "rev-parse", "HEAD^{tree}"),
    )
    command = _command(authority, "source.read", target="source-policy")
    snapshot = authority.admit_source(service, command, request)
    assert authority.readback_source(service, command, snapshot) == snapshot
    with authority._connect() as connection:
        connection.execute(
            "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s",
            (authority.context.grant_ref,),
        )
    with pytest.raises(SourceAuthorizationError):
        authority.readback_source(service, command, snapshot)
