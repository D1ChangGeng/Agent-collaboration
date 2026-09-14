"""Provision or serve a source-bound real Windows Codex receiver."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nacl.signing import SigningKey
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from runtime.receiver_config import ReceiverRuntimeConfig
from runtime.receiver_crypto import public_key, sign
from runtime.receiver_deployment import bind_process_config, dump_process_config, inspect_factory
from runtime.receiver_entry import load_callbacks, load_process_config
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.remote_endpoint import serve
from tools.runtime.p2_codex_half_loop import _certificate, _command, _json, _proof, _write
from runtime.domain import DomainAuthority
from runtime.enrollment_models import NodeEnrollment, RuntimeRegistration
from runtime.receiver_domain import (
    AuthorityTransportKeyRegistration, ConnectionReferenceRegistration,
    EndpointRegistrationCommand,
)
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.receiver_delivery import RemoteNodeEndpointAdapter, RemoteSenderDeployment


def _private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    user = subprocess.run(["whoami.exe"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls.exe", str(path), "/inheritance:r"], check=True, capture_output=True)
    subprocess.run(
        ["icacls.exe", str(path), "/grant:r", f"{user}:(OI)(CI)F", "/T", "/C"],
        check=True, capture_output=True,
    )


def _lock_file(path: Path) -> None:
    user = subprocess.run(["whoami.exe"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls.exe", str(path), "/inheritance:r"], check=True, capture_output=True)
    subprocess.run(["icacls.exe", str(path), "/grant:r", f"{user}:F"], check=True, capture_output=True)


def stage_capacity(root: Path, runtime_id: str) -> dict:
    for name in ("bin", "codex-home", "cwd", "home", "tmp", "artifacts", "state"):
        _private(root / name)
    native = next((Path(os.environ["LOCALAPPDATA"]) / "OpenAI/Codex/bin").rglob("codex.exe"))
    shutil.copyfile(native, root / "bin/codex.exe")
    for helper_name in (
        "codex-code-mode-host.exe", "codex-command-runner.exe",
        "codex-windows-sandbox-setup.exe",
    ):
        helper = native.parent / helper_name
        if not helper.is_file():
            raise RuntimeError("reviewed Windows Codex helper is missing: " + helper_name)
        shutil.copyfile(helper, root / "bin" / helper_name)
    import tomllib
    original = tomllib.loads((Path.home() / ".codex/config.toml").read_text(encoding="utf-8"))
    provider = original["model_providers"]["custom"]
    catalog_source = Path.home() / ".codex/models_cache.json"
    catalog = root / "codex-home/models.json"
    shutil.copyfile(catalog_source, catalog)
    quote = json.dumps
    config = "\n".join((
        f"model = {quote(original['model'])}",
        'model_reasoning_effort = "low"', 'model_provider = "custom"',
        f"model_catalog_json = {quote(str(catalog))}", 'approval_policy = "never"',
        'default_permissions = ":workspace"', 'allow_login_shell = false',
        'web_search = "disabled"', "", "[features]", "multi_agent = false",
        "multi_agent_v2 = false", "shell_tool = false", "request_permissions_tool = false",
        "apps = false", "plugins = false", "recommended_plugins = false", "",
        "[windows]", 'sandbox = "unelevated"', "", 
        "[shell_environment_policy]", 'inherit = "none"', "", 
        "[model_providers.custom]",
        f"name = {quote(provider['name'])}", f"base_url = {quote(provider['base_url'])}",
        f"wire_api = {quote(provider['wire_api'])}",
        f"env_key = {quote(provider['env_key'])}",
        f"requires_openai_auth = {str(bool(provider.get('requires_openai_auth'))).lower()}", "",
    ))
    config_path = root / "codex-home/config.toml"
    config_path.write_text(config, encoding="utf-8")
    schema = (
        Path(__file__).resolve().parents[2]
        / "runtime_tests/schema-0.153.4/codex_app_server_protocol.schemas.json"
    )
    settings = {
        "schema_version":"acs-receiver-codex-factory/1", "binding_id":"p2-windows-codex",
        "capacity_attempt_id":"p2-windows-capacity", "executable":str(root / "bin/codex.exe"),
        "executable_sha256":hashlib.sha256((root / "bin/codex.exe").read_bytes()).hexdigest(),
        "codex_version":"0.153.4", "protocol_schema":str(schema),
        "protocol_schema_sha256":hashlib.sha256(schema.read_bytes()).hexdigest(),
        "cwd":str(root / "cwd"), "codex_home":str(root / "codex-home"),
        "config_sha256":hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "permission_profile":":workspace", "model":original["model"],
        "driver_journal":str(root / "state/driver.sqlite"),
        "node_journal":str(root / "state/node.sqlite"),
        "systemd_environment_dir":str(root / "state/windows-job"),
        "artifact_root":str(root / "artifacts"), "runtime_id":runtime_id,
        "spawn_operation_id":"p2-windows-spawn", "spawn_command_id":"p2-windows-spawn-command",
        "spawn_message_id":"p2-windows-spawn-message", "close_operation_id":"p2-windows-close",
        "close_command_id":"p2-windows-close-command", "close_message_id":"p2-windows-close-message",
        "collector_max_reads":120, "collector_interval_seconds":0.5,
    }
    for path in root.rglob("*"):
        if path.is_file(): _lock_file(path)
    return settings


def provision(args):
    root = args.output.resolve(); _private(root)
    base = _json(args.profile)["postgres_dsn"]
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(args.schema_name)))
    dsn = make_conninfo(base, options=f"-c search_path={args.schema_name} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    authority.initialize()
    authority.bootstrap_local_grant((
        "work_item.create", "work_item.read", "enrollment.manage", "receiver.manage",
        "delivery.manage", "message.send", "message.read", "runtime.invoke",
    ))
    node = DomainAuthority(dsn, context=__import__("dataclasses").replace(
        authority.context, principal_ref="p2-windows-node", grant_ref="grant:p2-windows-node"))
    node.bootstrap_local_grant(("runtime.register","attempt.register","execution.record",
        "endpoint.register","delivery.prepare","delivery.dispatch","delivery.readback",
        "delivery.recover","work_item.read"))
    node_key, authority_key = SigningKey.generate(), SigningKey.generate()
    node_seed, authority_seed = root / "node.seed", root / "authority.seed"
    node_seed.write_text(node_key.encode().hex()); authority_seed.write_text(authority_key.encode().hex())
    runtime_id="p2-windows-runtime"; node_id="p2-windows-node"; boot="p2-windows-boot"
    expiry=datetime.now(UTC)+timedelta(hours=1)
    authority.enroll_node(_command(authority,"node.enroll","node",node_id), NodeEnrollment(
        scope_id="local-scope",agent_slot_id="local-slot",observer_grant_ref=node.context.grant_ref,
        machine_id=args.machine_id,boot_incarnation=boot,public_key=public_key(node_key),expires_at=expiry))
    rr=RuntimeRegistration(node_id=node_id,node_binding_revision=1,provider="codex-app-server",
        producer_grant_ref=authority.context.grant_ref,expires_at=expiry-timedelta(minutes=5))
    rc=_command(node,"runtime.register","runtime",runtime_id)
    node.register_runtime(rc,rr,_proof(node,node_key,node_id,rc,{"request":rr.model_dump(mode="json")}))
    key_id="p2-windows-authority-key"
    authority.register_authority_transport_key(_command(authority,"receiver.key.register",
        "authority_transport_key",key_id),AuthorityTransportKeyRegistration(key_id=key_id,
        revision=1,public_key=public_key(authority_key),expires_at=expiry-timedelta(minutes=5)))
    connection_ref="p2-windows-private"
    authority.register_receiver_connection(_command(authority,"receiver.connection.register","connection",
        connection_ref),ConnectionReferenceRegistration(connection_ref=connection_ref,revision=1,
        locator_host=args.host,locator_port=args.port,route_class=args.route_class,
        policy_digest=hashlib.sha256(args.tree.encode()).hexdigest(),
        expires_at=expiry-timedelta(minutes=5)))
    cert,tls_key,cert_sha=_certificate(root,args.host)
    with authority._connect() as c: node_key_id=c.execute("select key_id from enrolled_node_bindings where tenant_id=%s and node_id=%s and binding_revision=1",(authority.tenant_id,node_id)).fetchone()[0]
    provisional=EndpointRegistration(registration_id="p2-windows-registration",endpoint_id="p2-windows-endpoint",
        endpoint_revision=1,connection_ref=connection_ref,tenant_id=authority.tenant_id,
        authority_id=authority.context.authority_id,authority_incarnation=authority.context.authority_incarnation,
        node_id=node_id,node_binding_revision=1,runtime_id=runtime_id,runtime_revision=1,machine_id=args.machine_id,
        boot_incarnation=boot,scope_id="local-scope",agent_slot_id="local-slot",tls_certificate_sha256=cert_sha,
        config_sha256="0"*64,expires_at=datetime.now(UTC)+timedelta(minutes=4))
    binding=EndpointBinding(registration=provisional,locator_host=args.host,locator_port=args.port,
        route_class=args.route_class,node_key_id=node_key_id,node_public_key=public_key(node_key),registration_signature=sign(node_key,provisional))
    settings=stage_capacity(root,runtime_id)
    factory,_,_,_=inspect_factory("runtime_deployment.receiver_codex:callbacks",settings=settings)
    config=ReceiverRuntimeConfig(binding=binding,authority_key_id=key_id,authority_key_revision=1,
        authority_public_key=public_key(authority_key),authority_public_key_fingerprint=hashlib.sha256(bytes.fromhex(public_key(authority_key))).hexdigest(),
        tls_cert_path=str(cert),tls_key_path=str(tls_key),node_signing_key_path=str(node_seed),ledger_path=str(root/"state/receiver.sqlite"),
        expected_boot_incarnation=boot,journal_generation=1)
    if args.listen_host:
        config = __import__("dataclasses").replace(
            config, listen_host=args.listen_host, listen_port=args.listen_port,
        )
    process=bind_process_config(config,factory,node_key); registration=process.runtime.binding.registration
    ec=_command(node,"endpoint.register","endpoint",registration.endpoint_id)
    ni={"registration":registration.model_dump(mode="json"),"registration_signature":process.runtime.binding.registration_signature}
    node.register_receiver_endpoint(ec,EndpointRegistrationCommand(registration=registration,
        registration_signature=process.runtime.binding.registration_signature,
        proof=_proof(node,node_key,node_id,ec,ni,ttl_seconds=300)))
    _write(root/"receiver-process.json",json.loads(dump_process_config(process)))
    for path in root.rglob("*"):
        if path.is_file(): _lock_file(path)
    state = {
        "schema_version": "acs-p2-windows-receiver-state/1",
        "schema_name": args.schema_name,
        "source_commit": args.commit,
        "source_tree": args.tree,
        "endpoint_id": registration.endpoint_id,
        "endpoint_revision": registration.endpoint_revision,
        "machine_id": args.machine_id,
        "node_id": node_id,
        "boot_incarnation": boot,
        "runtime_id": runtime_id,
        "authority_seed_path": str(authority_seed),
        "receiver_process_sha256": hashlib.sha256((root / "receiver-process.json").read_bytes()).hexdigest(),
    }
    _write(root / "state.json", state)
    _lock_file(root / "state.json")
    print(json.dumps({"status":"ready", **state},sort_keys=True))


def run(args):
    process=load_process_config(args.config); callbacks=load_callbacks(process)
    serve(process.runtime,authorize_current=callbacks.authorize_current,native_invoke=callbacks.native_invoke,
          shutdown_callback=callbacks.close)


def send(args):
    state = _json(args.state)
    base = _json(args.profile)["postgres_dsn"]
    dsn = make_conninfo(base, options=f"-c search_path={state['schema_name']} -c lock_timeout=5000")
    authority = DomainAuthority(dsn)
    signing = SigningKey(bytes.fromhex(args.authority_seed.read_text().strip()))
    endpoint = RemoteNodeEndpointAdapter(
        authority, state["endpoint_id"],
        RemoteSenderDeployment(
            authority_signing_key=signing,
            expected_boot_incarnation=state["boot_incarnation"], journal_generation=1,
        ), timeout=10,
    )
    service = DeliveryService(authority, {state["endpoint_id"]: endpoint})
    service.bind_endpoint(
        _command(authority, "message.bind", "message", state["endpoint_id"]),
        EndpointBindingRequest(
            scope_id="local-scope", agent_slot_id="local-slot",
            expires_at=datetime.now(UTC) + timedelta(minutes=3),
        ),
    )
    work_id = "p2-reverse-work-" + args.suffix
    authority.create_work_item(
        _command(authority, "work_item.create", "work_item", work_id),
        "local-scope", "local-slot", state["source_commit"],
    )
    sentinel = "P2-CODEX-LINUX-TO-WINDOWS-" + args.suffix
    message_id = "p2-reverse-message-" + args.suffix
    command = _command(authority, "message.send", "message", message_id)
    packet = DeliveryPacket(
        work_item_id=work_id, target_scope_id="local-scope", target_agent_slot_id="local-slot",
        accepted_revision=0, goal="Prove authenticated Linux-to-Windows P2 Codex delivery",
        accepted_state_summary="Opposite direction passed on prior baseline; this run binds current HEAD",
        request="Return exactly this sentinel and no other text: " + sentinel + ". Do not call tools and do not delegate.",
        constraints=("one native Codex turn", "no delegation", "no tool calls"),
        source_baseline=state["source_commit"],
        context_digests=(hashlib.sha256(state["source_tree"].encode()).hexdigest(),),
        expected_response=sentinel,
        required_evidence=("PostgreSQL", "receiver SQLite", "Driver journal", "Node outbox", "Windows Job Object"),
        activation="invoke", deadline=datetime.now(UTC) + timedelta(minutes=4),
        maximum_attempts=1, retry_delay_seconds=1,
    )
    queued = service.send_message(command, packet, endpoint_id=state["endpoint_id"], binding_revision=1)
    result = DeliveryDispatcher(service, worker_id="linux-p2-sender").dispatch({
        "tenant_id": authority.tenant_id, "message_id": message_id, "operation_id": queued.operation_id,
    })
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with authority._connect() as connection:
            row = connection.execute(
                "SELECT state,receipt_high_water FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
                (authority.tenant_id, message_id),
            ).fetchone()
        if row and row[1] == "response_received":
            break
        time.sleep(1)
    with authority._connect() as connection:
        message = connection.execute(
            "SELECT state,receipt_high_water,attempts,activation_node_id,activation_machine_id "
            "FROM delivery_messages WHERE tenant_id=%s AND message_id=%s",
            (authority.tenant_id, message_id),
        ).fetchone()
        receipts = connection.execute(
            "SELECT layer,receipt_id FROM delivery_receipts WHERE tenant_id=%s AND message_id=%s ORDER BY observed_at",
            (authority.tenant_id, message_id),
        ).fetchall()
    evidence = {
        "schema_version":"acs-p2-reverse-half-loop-evidence/1", "status":"blocked",
        "reason":"Reverse half loop evidence; full bidirectional aggregation and independent review pending",
        "source_commit":state["source_commit"], "source_tree":state["source_tree"],
        "linux_sender_machine":args.linux_machine_id, "windows_receiver_machine":state["machine_id"],
        "runtime_transport":"direct TLS 1.3 to registered Windows private endpoint",
        "dispatch_result":result, "message":list(message) if message else None,
        "receipts":[list(row) for row in receipts], "message_id":message_id,
        "operation_id":queued.operation_id,
        "expected_sentinel_sha256":hashlib.sha256(sentinel.encode()).hexdigest(),
    }
    _write(args.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if message and message[1] == "response_received" else 2


def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="action",required=True)
    a=s.add_parser("provision"); a.add_argument("--profile",type=Path,required=True); a.add_argument("--output",type=Path,required=True)
    a.add_argument("--host",required=True); a.add_argument("--port",type=int,required=True); a.add_argument("--route-class",choices=("private","tunnel"),default="private"); a.add_argument("--listen-host"); a.add_argument("--listen-port",type=int); a.add_argument("--machine-id",required=True); a.add_argument("--tree",required=True); a.add_argument("--commit",required=True); a.add_argument("--schema-name",required=True)
    b=s.add_parser("serve"); b.add_argument("--config",type=Path,required=True)
    c=s.add_parser("send"); c.add_argument("--profile",type=Path,required=True); c.add_argument("--state",type=Path,required=True); c.add_argument("--authority-seed",type=Path,required=True); c.add_argument("--output",type=Path,required=True); c.add_argument("--suffix",required=True); c.add_argument("--linux-machine-id",required=True)
    x=p.parse_args(); return provision(x) if x.action=="provision" else run(x) if x.action=="serve" else send(x)
if __name__=="__main__": main()
