"""Real installed wheel and PostgreSQL/public-tool smoke; scripted, no model."""
import hashlib
import importlib.metadata
import json
import os
import secrets
import sys
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[2]
candidate = root / "dist/candidates/acs-maintenance-20261101-dced06b"
installed = candidate / "installed"
sys.path.insert(0, str(installed))
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import runtime.domain
from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_service import ProjectService
from runtime.surfaces import PAYLOADS, SharedService

assert Path(runtime.domain.__file__).is_relative_to(installed)
catalog = json.loads((root / "docs/runtime/p2-mcp-tool-contract.json").read_text())
source_files = [path for directory in (root / "runtime", root / "runtime_deployment")
                for path in directory.rglob("*") if path.suffix in {".py", ".sql"}]
assert all((installed / path.relative_to(root)).read_bytes() == path.read_bytes() for path in source_files)
assert not (installed / "runtime/team_policy.py").exists()
wheel = next(candidate.glob("*.whl"))
with zipfile.ZipFile(wheel) as packed:
    assert not any(name.startswith("runtime_tests/") for name in packed.namelist())
scripts = sorted(point.name for point in importlib.metadata.distribution("agent-collaboration-runtime").entry_points)
assert "acs-human-bridge" not in scripts
assert not any(hasattr(DomainAuthority, name) for name in ("create_work_item", "register_attempt", "leases", "record_review"))
base = os.environ["ACS_COMMUNICATION_TEST_DSN"]
assert conninfo_to_dict(base)["dbname"] == "acs_communication_test"
schema = "wheel_test_" + uuid.uuid4().hex
with psycopg.connect(base, autocommit=True) as connection:
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
dsn = make_conninfo(base, options=f"-c search_path={schema} -c statement_timeout=10000")
try:
    secret = secrets.token_urlsafe(32)
    context = AuthenticatedContext("tenant:" + schema, "acs-p1-authority", "local-1", "wheel:root", "wheel:root-grant",
                                   hashlib.sha256(secret.encode()).hexdigest())
    domain = DomainAuthority(dsn, context=context)
    domain.initialize()
    permissions = {"project.adopt", "profile.root_manager", "message.send", "message.read", "runtime.invoke", "delivery.manage"}
    for tool in catalog["tools"].values():
        permissions.update(tool["security_scopes"])
    domain.bootstrap_local_grant(tuple(sorted(permissions)))
    project = ProjectService(SharedService(domain, LocalCredentialAuthenticator(context)), catalog, profile="root_manager")
    project.initialize()
    now = datetime.now(UTC)
    command = CommandEnvelope(command_type="project.adopt", command_id="wheel-adopt", idempotency_key="wheel-adopt",
        correlation_id="wheel-adopt", tenant_id=context.tenant_id, authority_id=context.authority_id,
        authority_incarnation=context.authority_incarnation, principal_ref=context.principal_ref, grant_ref=context.grant_ref,
        target_kind="project", target_id="wheel-project", expected_revision=0, issued_at=now, deadline=now+timedelta(minutes=3))
    project.admit_project(command, project_id="wheel-project", root_id="wheel-root", scope_id="local-scope", agent_slot_id="local-slot",
                          name="Isolated wheel check", context_manifest={}, credential=secret)
    a = McpRuntime(project, lambda: secret)
    def call(client, name, **values):
        result = client.call(name, {"project_id": "wheel-project", **values})["structuredContent"]
        assert result["ok"], result
        return result
    binding = call(a, "configure_team", prepare_native=False,
        members=[{"agent_slot_id": "wheel-b", "principal_ref": "wheel:b"}])["data"]["caller_bindings"][0]
    b_secret = secrets.token_urlsafe(32)
    b_context = replace(context, principal_ref="wheel:b", grant_ref=binding["grant_ref"], agent_slot_id="wheel-b",
                        credential_hash=hashlib.sha256(b_secret.encode()).hexdigest())
    b = McpRuntime(ProjectService(SharedService(DomainAuthority(dsn, context=b_context), LocalCredentialAuthenticator(b_context)),
                                  catalog, profile="engineer"), lambda: b_secret)
    sent = call(a, "send_message", to="collaborator:wheel-project:wheel-b", content="Verify installed wheel", activation="message_only")["data"]
    inbox = call(b, "check_inbox", **{"with": ""})["data"]["items"]
    assert len(inbox) == 1 and inbox[0]["message_handle"] == sent["message_handle"]
    original = call(b, "read_message", handle=sent["message_handle"])["data"]
    call(b, "send_message", to=original["from"], content="Installed wheel reply", reply_to=[sent["message_handle"]], activation="message_only")
    observed = call(a, "wait_for_response", handles=[sent["message_handle"]], timeout_seconds=0)
    assert observed["state"] == "satisfied"
    with psycopg.connect(dsn) as connection:
        counts = {name: connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]
                  for name in ("communication_messages", "communication_replies")}
        absent = ["work_items", "attempts", "accepted_state_revisions", "leases", "effects", "reviews",
                  "artifacts", "native_response_observations", "collaboration_handoffs"]
        assert all(connection.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None for name in absent)
        assert connection.execute("SELECT schema_version FROM runtime_schema_metadata WHERE schema_name='acs-communication-core'").fetchone() == ("2",)
        assert connection.execute("SELECT attnotnull FROM pg_attribute WHERE attrelid='delivery_transport_admissions'::regclass AND attname='accepted_revision'").fetchone() == (False,)
        table_count = connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname=current_schema()").fetchone()[0]
        assert table_count == 46
    with zipfile.ZipFile(wheel) as packed:
        assert not any(name.startswith("runtime/schema") or name=="runtime/project_control_schema.sql" for name in packed.namelist())
    facts = {"evidence_class": "scripted public API, real installed wheel/PostgreSQL, no model",
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "wheel": str(wheel),
        "installed_runtime": runtime.domain.__file__, "exact_source_files": len(source_files), "entry_points": scripts,
        "technical_commands": sorted(PAYLOADS), "counts": counts,
        "schema_layout": "current communication core 2 / project 2", "table_count": table_count, "retired_tables_absent": absent}
finally:
    assert schema.startswith("wheel_test_") and len(schema) == 43
    with psycopg.connect(base, autocommit=True) as connection:
        assert connection.execute("SELECT current_database()").fetchone()[0] == "acs_communication_test"
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
output = root / "integration_evidence/acs-maintenance-20261101/installed-candidate.json"
output.write_text(json.dumps(facts, indent=2), encoding="utf-8")
print(json.dumps({"exact_source_files": len(source_files), "counts": counts, "wheel_sha256": facts["wheel_sha256"]}))
