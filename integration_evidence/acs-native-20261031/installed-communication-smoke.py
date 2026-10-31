"""Run with the isolated installed wheel's Python, outside the source checkout.

This uses real PostgreSQL and public ACS tools; it does not request a model.
Only the uniquely owned schema in the explicitly named test database is removed.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import runtime
from runtime.auth import LocalCredentialAuthenticator
from runtime.domain import DomainAuthority
from runtime.mcp_runtime import McpRuntime
from runtime.models import CommandEnvelope
from runtime.project_service import ProjectService
from runtime.surfaces import SharedService

installed = Path(runtime.__file__).resolve().parent
assert "site-packages" in installed.parts, "This probe must use an installed wheel"
base = os.environ["ACS_COMMUNICATION_TEST_DSN"]
assert conninfo_to_dict(base)["dbname"] == "acs_communication_test"
assert conninfo_to_dict(base)["host"] == "127.0.0.1"
schema = "installed_communication_" + uuid.uuid4().hex
assert schema.startswith("installed_communication_") and len(schema) == 56
catalog = json.loads(Path(os.environ["ACS_INSTALLED_TEST_CATALOG"]).read_text(encoding="utf-8"))
with psycopg.connect(base, autocommit=True) as connection:
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
dsn = make_conninfo(base, options=f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000")
try:
    authority = DomainAuthority(dsn)
    authority.initialize()
    permissions = {"project.adopt", "profile.root_manager", "grants.manage", "collaborators.manage"}
    for tool in catalog["tools"].values():
        permissions.update(tool["security_scopes"])
    authority.bootstrap_local_grant(tuple(permissions))
    token = uuid.uuid4().hex
    authority.context = replace(authority.context, trusted_client=True,
                                credential_hash=hashlib.sha256(token.encode()).hexdigest())
    projects = ProjectService(SharedService(authority, LocalCredentialAuthenticator(authority.context)),
                              catalog, profile="root_manager")
    projects.initialize()
    now = datetime.now(UTC)
    context = authority.context
    adopt = CommandEnvelope(command_id="adopt-"+uuid.uuid4().hex, command_type="project.adopt",
        idempotency_key=uuid.uuid4().hex, correlation_id="installed-smoke", tenant_id=context.tenant_id,
        authority_id=context.authority_id, authority_incarnation=context.authority_incarnation,
        principal_ref=context.principal_ref, grant_ref=context.grant_ref, target_kind="project",
        target_id="installed-test", expected_revision=0, issued_at=now, deadline=now+timedelta(minutes=2))
    projects.admit_project(adopt, project_id="installed-test", root_id="installed-test-root", scope_id="local-scope",
        agent_slot_id="local-slot", name="Installed package communication probe", context_manifest={}, credential=token)
    clients = {"client": McpRuntime(projects, lambda: token)}
    def call(actor, tool, **arguments):
        result = clients[actor].call(tool, {"project_id": "installed-test", **arguments})["structuredContent"]
        assert result["ok"], result
        return result
    configured = call("client", "configure_team", prepare_native=False, members=[
        {"agent_slot_id": "installed-a", "principal_ref": "agent:installed-a"},
        {"agent_slot_id": "installed-b", "principal_ref": "agent:installed-b"}])
    for binding in configured["data"]["caller_bindings"]:
        name = binding["agent_slot_id"].removeprefix("installed-")
        credential = uuid.uuid4().hex
        child = replace(context, **{key: binding[key] for key in ("agent_slot_id", "principal_ref", "grant_ref", "trusted_client")},
                        credential_hash=hashlib.sha256(credential.encode()).hexdigest())
        child_authority = DomainAuthority(dsn, context=child)
        clients[name] = McpRuntime(ProjectService(SharedService(child_authority, LocalCredentialAuthenticator(child)),
            catalog, profile=binding["profile"]), lambda value=credential: value)
    content = "Installed-package greeting " + uuid.uuid4().hex
    request = call("a", "send_message", to="collaborator:installed-test:installed-b", content=content,
                   activation="message_only")["data"]
    inbox = call("b", "check_inbox")["data"]["items"]
    assert inbox[0]["message_handle"] == request["message_handle"]
    original = call("b", "read_message", handle=inbox[0]["message_handle"])["data"]
    assert original["content"] == content and original["from"] == "collaborator:installed-test:installed-a"
    reply = call("b", "send_message", to=original["from"], content="Installed B received the original",
                 reply_to=[original["message_handle"]], activation="message_only")["data"]
    waited = call("a", "wait_for_response", handles=[request["message_handle"]], timeout_seconds=0)
    assert waited["state"] == "satisfied"
    assert waited["data"]["observations"][0]["reply"]["message_handle"] == reply["message_handle"]
    assert len(call("a", "list_messages")["data"]["items"]) == 2
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM work_items").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM accepted_state_revisions").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM communication_supervisors").fetchone()[0] == 2
    print(json.dumps({"installed_root": str(installed), "public_messages": 2, "explicit_replies": 1,
        "work_items": 0, "accepted_states": 0, "trusted_client_is_unbound": context.agent_slot_id is None,
        "native_model_requested": False, "test_schema": schema}))
finally:
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
