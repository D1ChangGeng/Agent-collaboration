"""Isolated loopback ACS Core HTTP/SSE server for Porpita opaque-box E2E tests.

Composed strictly from Agent-collaboration/runtime/* using temporary
directory storage and ephemeral PostgreSQL (schema or container). Never modifies
repository files.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from copy import copy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import anyio
import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse


def _resolve_agent_collab_root() -> Path:
    env_root = os.environ.get("PORPITA_E2E_AGENT_COLLAB_ROOT") or os.environ.get("AGENT_COLLAB_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if (candidate / "runtime" / "communication_http.py").is_file():
            return candidate
    for base in (Path(__file__).resolve(), Path.cwd().resolve()):
        for ancestor in (base, *base.parents):
            if (ancestor / "runtime" / "communication_http.py").is_file():
                return ancestor
    return Path(__file__).resolve().parents[2]


ROOT = _resolve_agent_collab_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts import LocalArtifactStore, WindowsArtifactStore
from runtime.auth import LocalCredentialAuthenticator
from runtime.codex_driver import (
    AuthorizedOperation,
    BindingIdentity,
    CodexAppServerDriver,
    DriverJournal,
    LaunchProfile,
    file_digest,
)
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_dispatch import maintain_communication_deliveries
from runtime.communication_event_storage import publish_event_intents
from runtime.communication_http import (
    CommunicationHttpError,
    CommunicationHttpLimits,
    create_communication_app,
)
from runtime.connection_clock import ConnectionClock
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_provider_registry import LocalExistingSessionProvider, NativeProviderRegistry
from runtime.native_view_models import NativeSelection, ProviderAdmission
from runtime.node import NodeJournal
from runtime.project_common import digest, handle
from runtime.project_service import ProjectService
from runtime.receiver_contract import ReceiverBinding
from runtime.scoped_artifacts import ScopedArtifactStores
from runtime.surface_config import CommunicationAttachmentSettings, CommunicationNativeLinkSettings
from runtime.surfaces import SharedService


CATALOG_PATH = ROOT / "docs" / "runtime" / "p2-mcp-tool-contract.json"
PROJECT_ID = "porpita-local"
SCOPE_ID = "local-scope"
PROVIDER_REF = "controlled-existing-provider"
RECEIVER_B = "endpoint-b"
RECEIVER_C = "endpoint-c"


def _install_loopback_pg_connect_resilience():
    """Retry bounded TCP handshake stalls (e.g., WSL2 port-relay timeouts) before any query runs."""
    import sys as _sys
    import time as _time
    import psycopg as _psycopg
    from psycopg.conninfo import conninfo_to_dict as _conninfo_to_dict

    if getattr(_psycopg.connect, "_e2e_loopback_wrapped", False):
        return
    _orig_connect = _psycopg.connect

    def _resilient_connect(*args, **kwargs):
        merged = dict(kwargs)
        dsn_str = args[0] if args else merged.get("conninfo", "")
        dsn_timeout = 0
        try:
            raw_t = _conninfo_to_dict(str(dsn_str)).get("connect_timeout")
            if raw_t is not None:
                dsn_timeout = int(raw_t)
        except Exception:
            dsn_timeout = 0
        kw_timeout = merged.get("connect_timeout")
        try:
            eff_timeout = int(kw_timeout) if kw_timeout is not None else dsn_timeout
        except Exception:
            eff_timeout = 0
        if eff_timeout < 15:
            merged["connect_timeout"] = 15
        last_err = None
        for attempt in range(6):
            try:
                return _orig_connect(*args, **merged)
            except _psycopg.OperationalError as err:
                msg = str(err).lower()
                transient = err.sqlstate is None and any(
                    frag in msg
                    for frag in (
                        "connection timeout expired",
                        "timeout expired",
                        "server closed the connection unexpectedly",
                        "connection reset by peer",
                        "ssl syscall error: eof detected",
                        "connection refused",
                        "cannot assign requested address",
                    )
                )
                if not transient or attempt == 5:
                    raise
                last_err = err
                _sys.stderr.write(
                    f"[e2e-loopback] pg connect retry {attempt + 1}/5: {type(err).__name__}: {err}\n"
                )
                _sys.stderr.flush()
                _time.sleep(0.1 * (2**attempt))
        raise last_err

    _resilient_connect._e2e_loopback_wrapped = True
    _psycopg.connect = _resilient_connect


class InProcessCodexWire:
    """Controlled in-process JSON-RPC wire for DriverJournal native-source provenance."""

    def __init__(self, expected_thread_id: str):
        self.expected_thread_id = expected_thread_id
        self.calls: list[tuple[str, dict, str]] = []

    def request(self, method, params, *, timeout, request_id, before_send, on_dispatch):
        assert method == "turn/start" and params.get("threadId") == self.expected_thread_id
        before_send()
        on_dispatch()
        self.calls.append((method, params, request_id))
        return {"turn": {"id": f"protocol-turn-{len(self.calls)}", "status": "inProgress"}}

    def drain_events(self):
        return []

    def close(self):
        return None


def _all_permissions(catalog: dict) -> tuple[str, ...]:
    perms = {
        "project.adopt",
        "profile.root_manager",
        "profile.engineer",
        "delivery.manage",
        "message.send",
        "message.read",
        "runtime.invoke",
        "runtime.read",
        "collaborators.manage",
        "grants.manage",
        "artifact.read",
        "artifact.write",
    }
    for definition in catalog.get("tools", {}).values():
        perms.update(definition.get("security_scopes", []))
    return tuple(sorted(perms))


def _command(authority: DomainAuthority, cmd_type: str, target_id: str, target_kind: str = "endpoint", rev: int = 0) -> CommandEnvelope:
    ctx = authority.context
    return CommandEnvelope(
        command_id=f"cmd-{uuid.uuid4().hex[:16]}",
        idempotency_key=f"idem-{uuid.uuid4().hex[:16]}",
        correlation_id=f"corr-{uuid.uuid4().hex[:12]}",
        command_type=cmd_type,
        target_kind=target_kind,
        target_id=target_id,
        expected_revision=rev,
        issued_at=authority.canonical_now(),
        tenant_id=ctx.tenant_id,
        authority_id=ctx.authority_id,
        authority_incarnation=ctx.authority_incarnation,
        principal_ref=ctx.principal_ref,
        grant_ref=ctx.grant_ref,
    )


def _setup_state(dsn: str, state: Path) -> dict:
    state.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    client_token = "e2e-client-" + secrets.token_hex(16)
    peer_b_token = "e2e-peer-b-" + secrets.token_hex(16)
    peer_c_token = "e2e-peer-c-" + secrets.token_hex(16)
    admin_token = "e2e-admin-" + secrets.token_hex(16)
    identity = secrets.token_hex(12)

    client_ctx = AuthenticatedContext(
        tenant_id="porpita-e2e-" + identity,
        authority_id="porpita-e2e-" + identity,
        authority_incarnation="e2e-inc-1",
        principal_ref="client:porpita-e2e-" + identity,
        grant_ref="identity:porpita-e2e-" + identity,
        credential_hash=hashlib.sha256(client_token.encode()).hexdigest(),
        trusted_client=True,
    )
    peer_b_ctx = replace(
        client_ctx,
        principal_ref="agent:peer-b",
        grant_ref="grant:peer-b-" + identity,
        agent_slot_id="slot-b",
        trusted_client=False,
        credential_hash=hashlib.sha256(peer_b_token.encode()).hexdigest(),
    )
    peer_c_ctx = replace(
        client_ctx,
        principal_ref="agent:peer-c",
        grant_ref="grant:peer-c-" + identity,
        agent_slot_id="slot-c",
        trusted_client=False,
        credential_hash=hashlib.sha256(peer_c_token.encode()).hexdigest(),
    )

    authority = DomainAuthority(
        dsn,
        context=client_ctx,
        authority_binding=(client_ctx.authority_id, client_ctx.authority_incarnation),
        access_mode="owner",
    )
    authority._communication_client_api_enabled = True
    authority._communication_events_enabled = True
    authority._notification_frontiers_enabled = True
    authority._wait_ingress_recovery_enabled = True
    authority._communication_attachment_settings = CommunicationAttachmentSettings()
    authority._communication_attachments_enabled = True
    authority._communication_native_links_enabled = True
    authority._communication_native_link_settings = CommunicationNativeLinkSettings()
    authority._receiver_lifecycle_catalog = catalog

    authority.initialize()
    authority.bootstrap_local_grant(_all_permissions(catalog), preserve_existing=True)

    shared = SharedService(authority, LocalCredentialAuthenticator(client_ctx))
    projects = ProjectService(shared, catalog, profile="operator")
    projects.initialize()

    projects.admit_project(
        _command(authority, "project.adopt", PROJECT_ID, target_kind="project", rev=0),
        project_id=PROJECT_ID,
        root_id=PROJECT_ID,
        scope_id=SCOPE_ID,
        agent_slot_id=None,
        name="Porpita",
        context_manifest={},
        credential=client_token,
    )

    client_address = handle("client", PROJECT_ID, digest([client_ctx.authority_id, client_ctx.principal_ref]))
    all_perms_json = json.dumps(_all_permissions(catalog))
    with authority._connect() as connection:
        connection.execute(
            "INSERT INTO communication_clients(tenant_id,project_id,address,principal_ref) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (client_ctx.tenant_id, PROJECT_ID, client_address, client_ctx.principal_ref),
        )
        for slot, ctx in (("slot-b", peer_b_ctx), ("slot-c", peer_c_ctx)):
            connection.execute(
                "INSERT INTO agent_slots VALUES (%s,%s,%s,'active') ON CONFLICT DO NOTHING",
                (slot, ctx.tenant_id, SCOPE_ID),
            )
            connection.execute(
                "INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,"
                "scope_id,permissions,expires_at,revoked_at,identity_only) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+interval '365 days',NULL,FALSE) "
                "ON CONFLICT (grant_ref) DO UPDATE SET permissions=EXCLUDED.permissions,expires_at=EXCLUDED.expires_at,revoked_at=NULL,identity_only=FALSE",
                (
                    ctx.grant_ref,
                    ctx.tenant_id,
                    ctx.principal_ref,
                    ctx.authority_id,
                    ctx.authority_incarnation,
                    SCOPE_ID,
                    all_perms_json,
                ),
            )
            connection.execute(
                "INSERT INTO collaboration_memberships VALUES (%s,%s,%s,%s,'engineer',%s)",
                (ctx.tenant_id, PROJECT_ID, ctx.principal_ref, ctx.grant_ref, slot),
            )

    # Bind endpoints using durable NodeJournals in state dir (supports_invoke=True)
    setup_driver = SimpleNamespace(evidence_class="native_driver_observation")
    endpoint_b = LocalNodeEndpoint(NodeJournal(state / "node-b.sqlite"), SCOPE_ID, "slot-b", setup_driver)
    endpoint_c = LocalNodeEndpoint(NodeJournal(state / "node-c.sqlite"), SCOPE_ID, "slot-c", setup_driver)
    delivery = DeliveryService(authority, {RECEIVER_B: endpoint_b, RECEIVER_C: endpoint_c})
    for rid, slot in ((RECEIVER_B, "slot-b"), (RECEIVER_C, "slot-c")):
        delivery.bind_endpoint(
            _command(authority, "message.bind", rid, target_kind="message", rev=0),
            EndpointBindingRequest(
                scope_id=SCOPE_ID,
                agent_slot_id=slot,
                expires_at=authority.canonical_now() + timedelta(hours=24),
            ),
        )

    state_meta = {
        "client_ctx": asdict(client_ctx),
        "peer_b_ctx": asdict(peer_b_ctx),
        "peer_c_ctx": asdict(peer_c_ctx),
        "boot_b": endpoint_b.identity.boot_incarnation,
        "boot_c": endpoint_c.identity.boot_incarnation,
        "tokens": {
            "client": client_token,
            "peer_b": peer_b_token,
            "peer_c": peer_c_token,
            "admin": admin_token,
        },
        "project_id": PROJECT_ID,
        "scope_id": SCOPE_ID,
        "client_address": client_address,
        "peer_b_address": f"collaborator:{PROJECT_ID}:slot-b",
        "peer_c_address": f"collaborator:{PROJECT_ID}:slot-c",
        "receiver_b": RECEIVER_B,
        "receiver_c": RECEIVER_C,
    }
    (state / "e2e-state.json").write_text(json.dumps(state_meta, indent=2) + "\n", encoding="utf-8")
    return state_meta


def _build_native_driver(state: Path, node_journal: NodeJournal, slot: str, clock=None):
    folder = state / f"native-{slot}"
    folder.mkdir(parents=True, exist_ok=True)
    executable = folder / "controlled-profile"
    schema = folder / "schema.json"
    home = folder / "home"
    if not executable.exists():
        executable.write_bytes(b"controlled Native profile; never executed")
    if not schema.exists():
        schema.write_text("{}", encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    config = home / "config.toml"
    if not config.exists():
        config.write_text('default_permissions="fixture"\napproval_policy="never"\n', encoding="utf-8")

    profile = LaunchProfile(
        str(executable),
        file_digest(executable),
        "0.153.2",
        str(schema),
        file_digest(schema),
        str(folder),
        str(home),
        file_digest(config),
        "fixture",
        {},
    )
    journal = DriverJournal(folder / "driver.sqlite", clock=clock)
    identity = BindingIdentity(
        node_journal.identity.node_id,
        node_journal.identity.boot_incarnation,
        "controlled-existing-runtime",
        "configured-capacity",
        slot,
        3,
    )
    driver = CodexAppServerDriver(
        f"controlled-driver-{slot}",
        profile,
        journal,
        identity=identity,
        check_current=lambda *_args: None,
        clock=clock,
    )
    driver.thread_id = "controlled-existing-session"
    driver.session_id = "controlled-existing-connection"
    driver.ownership = "exclusive_owned"
    driver.client = InProcessCodexWire(driver.thread_id)
    driver._inspect = lambda *_args: {"thread": {"status": {"type": "idle"}}, "turns": []}
    driver.inspect_readiness = lambda op, *, before_status: (
        driver.check_current(op, identity),
        before_status(),
        {"thread": {"status": {"type": "idle"}}, "turns": []},
    )[-1]

    def inspect_runtime():
        return {"state": "idle", "session_ref": driver.thread_id, "observation": "native_driver_readback"}

    adapter = NativeDeliveryAdapter(
        driver,
        authorize_invocation=lambda inv, _id: AuthorizedOperation(
            inv.invocation_id, inv.command_id, inv.message_id, inv.envelope.grant_ref, None
        ),
        clock=clock,
        inspect_runtime=inspect_runtime,
        record_handoff=True,
    )
    return driver, adapter


def create_server_app(dsn: str, state: Path, mode: str):
    _install_loopback_pg_connect_resilience()
    meta_path = state / "e2e-state.json"
    if not meta_path.exists():
        meta = _setup_state(dsn, state)
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    client_ctx = AuthenticatedContext(**meta["client_ctx"])
    peer_b_ctx = AuthenticatedContext(**meta["peer_b_ctx"])
    peer_c_ctx = AuthenticatedContext(**meta["peer_c_ctx"])
    tokens = meta["tokens"]

    p2_enabled = mode == "full"

    def make_authority(ctx: AuthenticatedContext, access_mode: str = "shared") -> DomainAuthority:
        auth = DomainAuthority(
            dsn,
            context=ctx,
            authority_binding=(ctx.authority_id, ctx.authority_incarnation),
            access_mode=access_mode,
        )
        auth._communication_client_api_enabled = True
        auth._communication_events_enabled = p2_enabled
        auth._notification_frontiers_enabled = True
        auth._wait_ingress_recovery_enabled = True
        auth._communication_maintenance_mode = "external"
        auth._communication_attachment_settings = CommunicationAttachmentSettings()
        auth._communication_attachments_enabled = p2_enabled
        auth._communication_native_links_enabled = True
        auth._communication_native_link_settings = CommunicationNativeLinkSettings()
        auth._receiver_lifecycle_catalog = catalog
        return auth

    owner_auth = make_authority(client_ctx, access_mode="owner")
    peer_b_auth = make_authority(peer_b_ctx)
    peer_c_auth = make_authority(peer_c_ctx)

    artifacts_dir = state / "attachments" / hashlib.sha256(SCOPE_ID.encode()).hexdigest()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = subprocess.run(
            ["whoami.exe"], capture_output=True, text=True, check=True
        ).stdout.strip()
        subprocess.run(
            ["icacls.exe", str(artifacts_dir), "/inheritance:r"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["icacls.exe", str(artifacts_dir), "/grant:r", f"{user}:(OI)(CI)F", "/T", "/C"],
            check=True,
            capture_output=True,
        )
    store_cls = WindowsArtifactStore if os.name == "nt" else LocalArtifactStore
    store = store_cls(artifacts_dir, SCOPE_ID, max_bytes=20 * 1024 * 1024)
    scoped_stores = ScopedArtifactStores([store])

    node_b = NodeJournal(state / "node-b.sqlite", boot_incarnation=meta["boot_b"])
    node_c = NodeJournal(state / "node-c.sqlite", boot_incarnation=meta["boot_c"])
    clock_b = ConnectionClock.from_authority(
        owner_auth,
        identity={
            "machine_id": node_b.identity.machine_id,
            "node_id": node_b.identity.node_id,
            "boot_incarnation": node_b.identity.boot_incarnation,
        },
    )
    clock_c = ConnectionClock.from_authority(
        owner_auth,
        identity={
            "machine_id": node_c.identity.machine_id,
            "node_id": node_c.identity.node_id,
            "boot_incarnation": node_c.identity.boot_incarnation,
        },
    )
    driver_b, adapter_b = _build_native_driver(state, node_b, "slot-b", clock=clock_b)
    driver_c, adapter_c = _build_native_driver(state, node_c, "slot-c", clock=clock_c)
    endpoint_b = LocalNodeEndpoint(node_b, SCOPE_ID, "slot-b", adapter_b)
    endpoint_c = LocalNodeEndpoint(node_c, SCOPE_ID, "slot-c", adapter_c)
    endpoints = {RECEIVER_B: endpoint_b, RECEIVER_C: endpoint_c}

    registry = NativeProviderRegistry(clock=clock_b.observation_time)
    for auth in (owner_auth, peer_b_auth, peer_c_auth):
        auth._artifact_store = scoped_stores
        auth._delivery_endpoints = endpoints
        auth._native_provider_registry = registry

    owner_projects = ProjectService(
        SharedService(owner_auth, LocalCredentialAuthenticator(client_ctx)), catalog, profile="operator"
    )
    peer_b_projects = ProjectService(
        SharedService(peer_b_auth, LocalCredentialAuthenticator(peer_b_ctx)), catalog, profile="engineer"
    )
    peer_c_projects = ProjectService(
        SharedService(peer_c_auth, LocalCredentialAuthenticator(peer_c_ctx)), catalog, profile="engineer"
    )
    for svc in (owner_projects, peer_b_projects, peer_c_projects):
        svc.artifacts = scoped_stores

    # Register LocalExistingSessionProvider + ProviderAdmission for endpoint-b
    client_comm = CommunicationClientService(owner_projects, tokens["client"])

    def _select_b(bound, cursor, root, _cmd):
        record = client_comm._receiver_records(bound, cursor, root, PROJECT_ID, RECEIVER_B)[0]
        return NativeSelection(
            tenant_id=bound.tenant_id,
            project_id=PROJECT_ID,
            scope_id=record["scope_id"],
            agent_slot_id=record["agent_slot_id"],
            binding=client_comm._receiver_binding(PROJECT_ID, record),
            node_id=record["node_id"],
            boot_incarnation=record["boot_incarnation"],
        )

    selected_b = client_comm._transaction(PROJECT_ID, "list_harnesses", _select_b)
    provider_b = LocalExistingSessionProvider(endpoint_b)
    admission_b = ProviderAdmission(provider_ref=PROVIDER_REF, native_authority="harness", selection=selected_b)
    registry.register(admission_b, provider_b)
    proof_b = registry.prove(PROVIDER_REF, "harness", selected_b)
    assert proof_b.state == "verified", f"proof_b not verified: {proof_b}"

    # Also register ProviderAdmission matching _original_selection (without provider_generation/native_session_ref)
    # Wait: NativeProviderRegistry.original_source uses resolve() which ignores None optional fields in actual_selection!
    # So the single admission_b works for BOTH NativeLink prove() AND include_native_source=true!

    token_map = {
        tokens["client"]: (owner_projects, client_ctx, "client"),
        tokens["peer_b"]: (peer_b_projects, peer_b_ctx, "peer_b"),
        tokens["peer_c"]: (peer_c_projects, peer_c_ctx, "peer_c"),
    }

    def project_provider(request: Request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise CommunicationHttpError("unauthenticated", "Bearer credential required.", status_code=401)
        token = header[7:]
        entry = token_map.get(token)
        if entry is None:
            raise CommunicationHttpError("unauthenticated", "Invalid bearer credential.", status_code=401)
        svc, ctx, _name = entry
        # Check whether the grant has been revoked in PostgreSQL!
        with svc.service.authority._connect() as conn:
            row = conn.execute(
                "SELECT revoked_at FROM grants WHERE tenant_id=%s AND grant_ref=%s",
                (ctx.tenant_id, ctx.grant_ref),
            ).fetchone()
            if row is None or row[0] is not None:
                raise CommunicationHttpError("authorization_denied", "Grant has been revoked.", status_code=403)
        return svc, token

    if p2_enabled:
        attachment = owner_auth._communication_attachment_settings
        native_links = owner_auth._communication_native_link_settings
        limits = CommunicationHttpLimits(
            attachment_bytes=attachment.file_bytes,
            attachment_count=attachment.message_count,
            attachment_total_bytes=attachment.message_bytes,
            attachment_staging_bytes=attachment.viewer_staging_bytes,
            attachment_project_staging_bytes=attachment.project_staging_bytes,
            attachment_staging_seconds=attachment.staging_seconds,
            native_link_count=native_links.links_per_scope,
            native_link_history_revisions=native_links.history_per_link,
            native_link_write_receipts=native_links.requests_per_viewer,
            native_link_metadata_bytes=native_links.metadata_bytes,
        )
        features = [
            "profile", "projects", "routes", "contacts", "messages",
            "send", "wait", "delivery", "operations", "conversations", "conversation_resolve",
            "conversation_detail", "read_state", "preferences", "drafts", "search",
            "receivers", "receiver_recovery", "notices", "snapshot", "events",
            "attachment_uploads", "attachments", "native_links", "native_source",
            "porpita_host_loopback_v1",
        ]
        event_replay_seconds = 7 * 86400
    else:
        native_links = owner_auth._communication_native_link_settings
        limits = CommunicationHttpLimits(
            native_link_count=native_links.links_per_scope,
            native_link_history_revisions=native_links.history_per_link,
            native_link_write_receipts=native_links.requests_per_viewer,
            native_link_metadata_bytes=native_links.metadata_bytes,
        )
        features = [
            "profile", "projects", "routes", "contacts", "messages",
            "send", "wait", "delivery", "operations", "conversations", "conversation_resolve",
            "conversation_detail", "receivers", "receiver_recovery", "notices",
            "native_links", "native_source", "porpita_host_loopback_v1",
        ]
        event_replay_seconds = 0

    public_meta = {
        "schema_version": "acs-client/1",
        "server_version": version("agent-collaboration-runtime"),
        "authority_id": client_ctx.authority_id,
        "authority_incarnation": client_ctx.authority_incarnation,
        "features": features,
        "limits": {
            key: getattr(limits, key)
            for key in (
                "message_bytes",
                "page_items",
                "attachment_count",
                "attachment_bytes",
                "attachment_total_bytes",
                "attachment_staging_bytes",
                "attachment_project_staging_bytes",
                "attachment_staging_seconds",
                "native_link_count",
                "native_link_history_revisions",
                "native_link_write_receipts",
                "native_link_metadata_bytes",
            )
        }
        | {"event_replay_seconds": event_replay_seconds},
        "adapter_protocol": "acs-adapter/1",
        "event_protocol": "acs-event/1",
    }

    import runtime.communication_http as _comm_http_mod
    import sys as _sys
    import traceback as _traceback

    recent_server_errors = []
    if not getattr(_comm_http_mod._problem, "_e2e_logged", False):
        _orig_problem = _comm_http_mod._problem

        def _logging_problem(request, error):
            if not isinstance(error, CommunicationHttpError):
                tb = "".join(_traceback.format_exception(type(error), error, error.__traceback__))
                _sys.stderr.write(f"[e2e-loopback] unhandled {request.method} {request.url.path}: {tb}\n")
                _sys.stderr.flush()
                recent_server_errors.append(
                    {
                        "method": request.method,
                        "path": request.url.path,
                        "type": type(error).__name__,
                        "error": str(error),
                        "traceback": tb[-4000:],
                    }
                )
                if len(recent_server_errors) > 20:
                    del recent_server_errors[:-20]
            return _orig_problem(request, error)

        _logging_problem._e2e_logged = True
        _comm_http_mod._problem = _logging_problem
        _comm_http_mod._problem._e2e_errors_sink = recent_server_errors
    elif hasattr(_comm_http_mod._problem, "_e2e_errors_sink"):
        recent_server_errors = _comm_http_mod._problem._e2e_errors_sink

    app = create_communication_app(project_provider, limits=limits, public_meta=public_meta)

    @app.get("/__e2e/errors")
    async def e2e_errors(request: Request):
        _require_admin(request)
        return {
            "errors": list(recent_server_errors),
            "httpErrors": list(recent_http_errors),
            "recentHttp": list(recent_http_trace),
        }

    recent_http_errors = []
    recent_http_trace = []
    fault_state = {"drop_next_send_response": False}

    @app.middleware("http")
    async def fault_injector(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/__e2e"):
            recent_http_trace.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                }
            )
            if len(recent_http_trace) > 30:
                del recent_http_trace[:-30]
        if response.status_code >= 400 and not request.url.path.startswith("/__e2e"):
            recent_http_errors.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                }
            )
            if len(recent_http_errors) > 30:
                del recent_http_errors[:-30]
        if (
            fault_state["drop_next_send_response"]
            and request.method == "POST"
            and request.url.path.endswith("/messages")
            and response.status_code in (200, 201)
        ):
            fault_state["drop_next_send_response"] = False
            return JSONResponse(
                {
                    "error": {
                        "code": "post_commit_observation_lost",
                        "message": "Simulated post-commit response timeout",
                        "retryable": True,
                        "effect_state": "committed",
                    }
                },
                status_code=503,
            )
        return response

    def _require_admin(request: Request):
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(header, "Bearer " + tokens["admin"]):
            raise CommunicationHttpError("unauthenticated", "Admin token required.", status_code=401)

    @app.get("/__e2e/info")
    async def e2e_info(request: Request):
        _require_admin(request)
        return {
            "project_id": PROJECT_ID,
            "scope_id": SCOPE_ID,
            "mode": mode,
            "tokens": {
                "client": tokens["client"],
                "peer_b": tokens["peer_b"],
                "peer_c": tokens["peer_c"],
            },
            "addresses": {
                "client": meta["client_address"],
                "peer_b": meta["peer_b_address"],
                "peer_c": meta["peer_c_address"],
            },
            "native_link_fixture": {
                "address": meta["peer_b_address"],
                "receiver_ref": RECEIVER_B,
                "expected_binding_epoch": selected_b.binding.binding_epoch,
                "provider_ref": PROVIDER_REF,
                "native_session_ref": proof_b.native_session_ref or "controlled-existing-session",
                "native_authority": "harness",
                "expected_revision": 0,
                "expected_host_ref": proof_b.host_ref,
                "expected_provider_generation": proof_b.provider_generation,
            },
        }

    async def _run_db_retry(fn, *, max_attempts=6):
        import psycopg

        transient_pg = (
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
            psycopg.errors.LockNotAvailable,
            psycopg.OperationalError,
        )
        for attempt in range(max_attempts):
            try:
                return await anyio.to_thread.run_sync(fn)
            except transient_pg:
                if attempt + 1 < max_attempts:
                    await anyio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def _send_with_committed_resume(comm_svc, body, req_id, *, max_attempts=8):
        import psycopg

        transient_pg = (
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
            psycopg.errors.LockNotAvailable,
            psycopg.OperationalError,
        )
        for attempt in range(max_attempts):
            try:
                return await anyio.to_thread.run_sync(
                    lambda: comm_svc.send(PROJECT_ID, body, client_request_id=req_id)
                )
            except CommunicationHttpError as err:
                if (
                    err.code == "observation_unavailable"
                    and err.effect_state == "committed"
                    and attempt + 1 < max_attempts
                ):
                    await anyio.sleep(0.05 * (attempt + 1))
                    continue
                raise
            except transient_pg:
                if attempt + 1 < max_attempts:
                    await anyio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    def _drain_event_intents():
        with owner_auth._connect() as conn:
            published = 0
            while publish_event_intents(conn, client_ctx.tenant_id, PROJECT_ID, limit=100):
                published += 1
            return published

    @app.post("/__e2e/peer-send")
    async def e2e_peer_send(request: Request):
        import sys
        import traceback

        _require_admin(request)
        try:
            payload = await request.json()
            actor = payload.get("actor", "peer_b")
            if actor == "peer_c":
                svc, tok = peer_c_projects, tokens["peer_c"]
            elif actor == "client":
                svc, tok = owner_projects, tokens["client"]
            else:
                svc, tok = peer_b_projects, tokens["peer_b"]
            comm_svc = CommunicationClientService(svc, tok)
            body = {
                "to": payload.get("to", meta["client_address"]),
                "content": payload["content"],
                "activation": payload.get("activation", "message_only"),
            }
            if payload.get("reply_to"):
                body["reply_to"] = payload["reply_to"]
            req_id = payload.get("client_request_id") or f"e2e-peer-{uuid.uuid4().hex[:12]}"
            res = await _send_with_committed_resume(comm_svc, body, req_id)
            # Dispatch pending & publish event intents deterministically
            dispatcher = DeliveryDispatcher(DeliveryService(owner_auth, endpoints))

            def _pending_rows():
                with owner_auth._connect() as conn:
                    return conn.execute(
                        "SELECT tenant_id, message_id, operation_id FROM delivery_messages "
                        "WHERE tenant_id=%s AND state IN ('queued','retry_wait')",
                        (client_ctx.tenant_id,),
                    ).fetchall()

            rows = await _run_db_retry(_pending_rows)
            for t_id, m_id, o_id in rows:
                try:
                    await anyio.to_thread.run_sync(
                        dispatcher.dispatch,
                        {"tenant_id": t_id, "message_id": m_id, "operation_id": o_id},
                    )
                except Exception:
                    pass
            await _run_db_retry(_drain_event_intents)
            return res
        except CommunicationHttpError:
            raise
        except Exception as err:
            traceback.print_exc(file=sys.stderr)
            raise CommunicationHttpError(
                "receiver_unavailable",
                f"E2E peer-send error: {type(err).__name__}",
                status_code=503,
                details={"exception": f"{type(err).__name__}: {err}"},
            ) from err

    @app.post("/__e2e/dispatch-pending")
    async def e2e_dispatch_pending(request: Request):
        _require_admin(request)
        dispatcher = DeliveryDispatcher(DeliveryService(owner_auth, endpoints))
        with owner_auth._connect() as conn:
            rows = conn.execute(
                "SELECT tenant_id, message_id, operation_id FROM delivery_messages "
                "WHERE tenant_id=%s AND state IN ('queued','retry_wait')",
                (client_ctx.tenant_id,),
            ).fetchall()
        dispatched = 0
        errors = []
        for t_id, m_id, o_id in rows:
            try:
                await anyio.to_thread.run_sync(
                    dispatcher.dispatch,
                    {"tenant_id": t_id, "message_id": m_id, "operation_id": o_id},
                )
                dispatched += 1
            except Exception as err:
                errors.append(f"{type(err).__name__}: {err}")
        published = 0
        with owner_auth._connect() as conn:
            while publish_event_intents(conn, client_ctx.tenant_id, PROJECT_ID, limit=100):
                published += 1
        return {"dispatched": dispatched, "published_batches": published, "errors": errors}

    @app.post("/__e2e/emit-notice")
    async def e2e_emit_notice(request: Request):
        import sys
        import traceback

        _require_admin(request)
        try:
            payload = await request.json()
            legacy_null = bool(payload.get("legacy_null_created_at", False))
            recipient = payload.get("recipient", meta["client_address"])
            code = payload.get("reason_code", "delivery_unconfirmed")
            notice_state = payload.get("state", "blocked")

            # Create a genuine communication_messages + delivery_messages record first
            comm_svc = CommunicationClientService(owner_projects, tokens["client"])
            notice_req_id = f"e2e-notice-origin-{uuid.uuid4().hex[:12]}"
            sent = await _send_with_committed_resume(
                comm_svc,
                {
                    "to": meta["peer_b_address"],
                    "content": "Notice origin message",
                    "activation": "message_only",
                },
                notice_req_id,
            )
            msg_handle = sent["message"]["message_handle"]
            msg_id = msg_handle.rsplit(":", 1)[-1]
            now_ts = None if legacy_null else owner_auth.canonical_now()

            def _insert_notice():
                with owner_auth._connect() as conn:
                    seq_row = conn.execute(
                        "INSERT INTO communication_notices(tenant_id,project_id,message_id,recipient,state,code) "
                        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING sequence",
                        (
                            client_ctx.tenant_id,
                            PROJECT_ID,
                            msg_id,
                            recipient,
                            notice_state,
                            code,
                        ),
                    ).fetchone()
                    conn.execute(
                        "UPDATE communication_client_notice_versions SET created_at=%s "
                        "WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s",
                        (now_ts, client_ctx.tenant_id, PROJECT_ID, msg_id, recipient),
                    )
                    ref_row = conn.execute(
                        "SELECT notice_ref FROM communication_client_notice_versions "
                        "WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s",
                        (client_ctx.tenant_id, PROJECT_ID, msg_id, recipient),
                    ).fetchone()
                    notice_ref = ref_row[0]
                    if p2_enabled:
                        from runtime.communication_notice_projection_storage import sync_notice_projection
                        from runtime.communication_client_notice_storage import NoticeStateIdentity

                        with conn.cursor() as cur:
                            sync_notice_projection(
                                cur,
                                NoticeStateIdentity(
                                    client_ctx.tenant_id,
                                    PROJECT_ID,
                                    client_ctx.principal_ref,
                                    msg_id,
                                    recipient,
                                ),
                            )
                    return seq_row[0] if seq_row else None, notice_ref

            seq_num, notice_ref = await _run_db_retry(_insert_notice)
            await _run_db_retry(_drain_event_intents)
            return {
                "message_id": msg_id,
                "sequence": seq_num,
                "notice_handle": f"notification:{PROJECT_ID}:{notice_ref}",
                "legacy_null_created_at": legacy_null,
            }
        except CommunicationHttpError:
            raise
        except Exception as err:
            traceback.print_exc(file=sys.stderr)
            raise CommunicationHttpError(
                "receiver_unavailable",
                f"E2E emit-notice error: {type(err).__name__}",
                status_code=503,
                details={"exception": f"{type(err).__name__}: {err}"},
            ) from err

    @app.post("/__e2e/revoke-token")
    async def e2e_revoke_token(request: Request):
        _require_admin(request)
        payload = await request.json()
        target = payload.get("actor", "client")
        ctx_map = {"client": client_ctx, "peer_b": peer_b_ctx, "peer_c": peer_c_ctx}
        target_ctx = ctx_map[target]
        with owner_auth._connect() as conn:
            conn.execute(
                "UPDATE grants SET revoked_at=clock_timestamp() WHERE tenant_id=%s AND grant_ref=%s",
                (target_ctx.tenant_id, target_ctx.grant_ref),
            )
        return {"revoked": target}

    @app.post("/__e2e/restore-token")
    async def e2e_restore_token(request: Request):
        _require_admin(request)
        payload = await request.json()
        target = payload.get("actor", "client")
        ctx_map = {"client": client_ctx, "peer_b": peer_b_ctx, "peer_c": peer_c_ctx}
        target_ctx = ctx_map[target]
        with owner_auth._connect() as conn:
            conn.execute(
                "UPDATE grants SET revoked_at=NULL WHERE tenant_id=%s AND grant_ref=%s",
                (target_ctx.tenant_id, target_ctx.grant_ref),
            )
        return {"restored": target}

    @app.post("/__e2e/fault")
    async def e2e_fault(request: Request):
        _require_admin(request)
        payload = await request.json()
        if "drop_next_send_response" in payload:
            fault_state["drop_next_send_response"] = bool(payload["drop_next_send_response"])
        return dict(fault_state)

    @asynccontextmanager
    async def lifespan(_application):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(maintain_communication_deliveries, owner_projects.service)
            try:
                yield
            finally:
                tasks.cancel_scope.cancel()
                driver_b.detach_transport()
                driver_c.detach_transport()
                store.close()

    app.router.lifespan_context = lifespan
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("setup", "serve"))
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mode", choices=("full", "p1_only"), default="full")
    args = parser.parse_args()
    _install_loopback_pg_connect_resilience()

    if args.action == "setup":
        meta = _setup_state(args.dsn, args.state)
        print(json.dumps({"ok": True, "project_id": meta["project_id"], "tokens": meta["tokens"]}), flush=True)
        return 0

    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be 1..65535")
    application = create_server_app(args.dsn, args.state, args.mode)
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=args.port,
        log_level="error",
        access_log=False,
        proxy_headers=False,
        timeout_keep_alive=65,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
