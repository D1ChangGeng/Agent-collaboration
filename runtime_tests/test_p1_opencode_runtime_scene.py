"""One no-model OpenCode HostNode delivery across real PG, Node and Temporal."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from runtime.codex_driver import AuthorizedOperation, BindingIdentity, DriverJournal
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.delivery_models import DeliveryPacket, EndpointBindingRequest
from runtime.delivery_node import LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeLaunchProfile, OpenCodeNativeDriver
from runtime.p1_codex_host_node import CodexHostRunPolicy, HostNodeRejected
from runtime.p1_opencode_host_node import (
    OpenCodeHostNodeEndpoint,
    OpenCodeHostRequest,
    OpenCodeHostUnixServer,
)
from runtime.systemd_supervisor import SystemdUserSupervisor
from runtime_tests.test_delivery import command, query
from tools.runtime.p1_opencode_projection import project_original_opencode_terminal
from tools.runtime.p1_opencode_readback import (
    OpenCodeReadbackRejected,
    read_original_opencode_scene,
)
from tools.runtime.p1_opencode_temporal import OpenCodeTemporalDispatcher


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(sys.platform != "linux", reason="actual PG, Temporal and Systemd required")
@pytest.mark.parametrize("current_change", [None, "grant_permissions", "scope_policy", "slot"])
def test_restricted_host_temporal_pg_node_one_fake_turn(setup, tmp_path, current_change):
    if os.geteuid() == 0 or os.environ.get("ACS_P1_TEMPORAL_ENDPOINT") != "127.0.0.1:7239":
        pytest.skip("reviewed non-root Temporal route required")
    if not os.environ.get("ACS_P1_TEMPORAL_NAMESPACE"):
        pytest.skip("reviewed Temporal namespace required")
    source_commit = os.environ.get("ACS_P1_SOURCE_COMMIT", "")
    source_tree = os.environ.get("ACS_P1_SOURCE_TREE", "")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit) or not re.fullmatch(
        r"[a-f0-9]{40}", source_tree
    ):
        pytest.skip("exact candidate commit/tree required")
    private = tmp_path / "opencode-host"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    roots = {
        name: private / name
        for name in ("home", "config", "data", "state", "cache", "input", "tmp", "bin", "ledger")
    }
    for directory in roots.values():
        directory.mkdir(mode=0o700)
    native = roots["bin"] / "opencode"
    fixture = (Path(__file__).parent / "p1_opencode_http_fixture.py").read_bytes()
    assert fixture.startswith(b'"""A no-model OpenCode-shaped HTTP process')
    native.write_bytes(b"#!" + sys.executable.encode() + b"\n" + fixture)
    native.chmod(0o500)
    schema = Path(__file__).parent / "schema-1.18.30/opencode-openapi.json"
    config_dir = roots["config"] / "opencode"
    config_dir.mkdir(mode=0o700)
    config = config_dir / "opencode.json"
    config.write_text(json.dumps({
        "permission": {"*": "deny", "task": "deny"},
        "default_agent": "engineer", "model": "fixture-provider/fixture-model",
        "agent": {"engineer": {
            "model": "fixture-provider/fixture-model",
            "permission": {"*": "deny", "task": "deny"},
        }},
        "plugin": [], "mcp": {},
    }), encoding="utf-8")
    config.chmod(0o600)
    run_id = "p1-opencode-" + uuid.uuid4().hex
    node = NodeJournal(
        roots["ledger"] / "node.sqlite", machine_id="fixture-machine",
        node_id="fixture-node", boot_incarnation="fixture-boot",
    )
    binding = BindingIdentity(
        node.node_id, node.boot_incarnation, "fixture-runtime", "fixture-execution", "local-slot", 1
    )
    profile = OpenCodeLaunchProfile(
        str(native), _sha(native), "1.18.30", str(schema), _sha(schema),
        str(roots["input"]), str(roots["home"]), str(roots["config"]),
        str(roots["data"]), str(roots["state"]), str(roots["cache"]),
        str(roots["tmp"]), _sha(config), "engineer", "fixture-provider",
        "fixture-model", {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "PYTHONPATH": str(Path(__file__).parents[1]),
            "ACS_P1_FIXTURE_SCHEMA": str(schema),
        },
    )
    supervisor = SystemdUserSupervisor(
        tasks_max=64, memory_max=1_073_741_824, cpu_quota_percent=100,
        termination_timeout=10,
    )
    driver = None
    server = None
    thread = None
    try:
        def current(operation: AuthorizedOperation, observed: BindingIdentity) -> None:
            assert observed == binding
            assert operation.grant_ref == setup.authority.context.grant_ref

        driver = OpenCodeNativeDriver(
            run_id + "-binding", profile, DriverJournal(roots["ledger"] / "driver.sqlite"),
            identity=binding, check_current=current, supervisor=supervisor,
        )

        def authorize(invocation, observed):
            assert observed == binding
            return AuthorizedOperation(
                invocation.invocation_id, invocation.command_id, invocation.message_id,
                invocation.envelope.grant_ref, invocation.envelope.packet.deadline,
            )

        adapter = NativeDeliveryAdapter(driver, authorize_invocation=authorize)
        endpoint = LocalNodeEndpoint(node, "local-scope", "local-slot", adapter)
        endpoint_id = "p1-opencode-" + uuid.uuid4().hex
        delivery = DeliveryService(setup.authority, {endpoint_id: endpoint})
        deadline = datetime.now(UTC) + timedelta(seconds=90)
        delivery.bind_endpoint(
            command(setup.authority, "message.bind", endpoint_id),
            EndpointBindingRequest(
                scope_id="local-scope", agent_slot_id="local-slot", expires_at=deadline,
            ),
        )
        policy_hash = hashlib.sha256(json.dumps(
            query(setup, "SELECT policy FROM scopes WHERE scope_id='local-scope'")[0][0],
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        policy = CodexHostRunPolicy(
            run_id=run_id,
            tenant_id=setup.authority.tenant_id,
            authority_id=setup.authority.context.authority_id,
            authority_incarnation=setup.authority.context.authority_incarnation,
            scope_id="local-scope", agent_slot_id="local-slot",
            scope_policy_sha256=policy_hash, endpoint_id=endpoint_id,
            source_commit=source_commit, native_sha256=_sha(native),
            config_sha256=_sha(config), deadline=deadline,
        )
        dispatcher = OpenCodeTemporalDispatcher(
            DeliveryDispatcher(delivery), endpoint="127.0.0.1:7239",
            namespace=os.environ["ACS_P1_TEMPORAL_NAMESPACE"],
            task_queue="p1-opencode-" + run_id.removeprefix("p1-opencode-"),
            deadline=deadline,
        )
        host = OpenCodeHostNodeEndpoint(
            policy, dispatcher, roots["ledger"] / "host.sqlite",
            native_path=native, config_path=config,
        )
        work_id = "work-" + uuid.uuid4().hex
        setup.authority.create_work_item(
            command(setup.authority, "work_item.create", work_id),
            "local-scope", "local-slot", source_commit,
        )
        message_id = "message-" + uuid.uuid4().hex
        send = command(
            setup.authority, "message.send", message_id, correlation_id=run_id,
        )
        packet = DeliveryPacket(
            work_item_id=work_id, target_scope_id="local-scope",
            target_agent_slot_id="local-slot", accepted_revision=0,
            goal="Observe one OpenCode fixture delivery", accepted_state_summary="revision zero",
            request="Reply with one fixture sentinel", source_baseline=source_commit,
            expected_response="synthetic final answer", activation="invoke",
            deadline=deadline - timedelta(seconds=2), maximum_attempts=1,
        )
        sent = delivery.send_message(
            send, packet, endpoint_id=endpoint_id, binding_revision=1,
        )
        request = OpenCodeHostRequest(
            action="dispatch", run_id=run_id, tenant_id=setup.authority.tenant_id,
            message_id=message_id, command_id=send.command_id,
            operation_id=sent.operation_id, endpoint_id=endpoint_id,
            source_commit=source_commit, native_sha256=_sha(native),
            config_sha256=_sha(config),
        )
        if current_change is not None:
            with setup.authority._connect() as database:
                if current_change == "grant_permissions":
                    database.execute(
                        "UPDATE grants SET permissions=%s WHERE grant_ref=%s",
                        (json.dumps(["message.read"]), setup.authority.context.grant_ref),
                    )
                elif current_change == "scope_policy":
                    database.execute(
                        "UPDATE scopes SET policy=%s WHERE scope_id='local-scope'",
                        (json.dumps({"revision": 2}),),
                    )
                else:
                    database.execute(
                        "UPDATE agent_slots SET status='revoked' "
                        "WHERE scope_id='local-scope' AND agent_slot_id='local-slot'"
                    )
            with pytest.raises(HostNodeRejected):
                host.start_native(request.internal(), AuthorizedOperation(
                    run_id + "-spawn", run_id + "-command-spawn", run_id + "-message-spawn",
                    setup.authority.context.grant_ref, deadline,
                ))
            assert driver.owned is None
            assert query(
                setup, "SELECT count(*) FROM delivery_attempts WHERE message_id=%s",
                (message_id,),
            ) == [(0,)]
            return
        boot = host.start_native(request.internal(), AuthorizedOperation(
            run_id + "-spawn", run_id + "-command-spawn", run_id + "-message-spawn",
            setup.authority.context.grant_ref, deadline,
        ))
        assert boot["verified"] is True and boot["remaining_pids"]
        server = OpenCodeHostUnixServer(host, roots["ledger"] / "host.sock")
        thread = threading.Thread(target=server.serve_one)
        thread.start()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(120)
            client.connect(str(server.socket_path))
            client.sendall(request.model_dump_json().encode() + b"\n")
            result = json.loads(client.recv(262144))
        thread.join(timeout=120)
        assert not thread.is_alive()
        assert result["schema_version"] == "acs-p1-opencode-host-result/1"
        assert result["status"] == "delivered"
        assert result["attempt_id"] and result["dispatch_id"]
        assert dispatcher.last["workflow_id"] == "acs-delivery/" + sent.operation_id
        assert dispatcher.last["provider_run_id"]
        assert query(setup, "SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (message_id,)) == [(1,)]
        assert query(setup, "SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
                            "AND layer='runtime_dispatched'", (message_id,)) == [(1,)]
        assert len(node.receipts(sent.operation_id)) >= 1
        with driver.journal._connect() as connection:
            prompts = connection.execute(
                "SELECT count(*) FROM driver_events WHERE kind='http_dispatch' "
                "AND body LIKE '%prompt_async%'"
            ).fetchone()[0]
        assert prompts == 1
        attempt_id = result["attempt_id"]
        projected = project_original_opencode_terminal(
            {
                "authority": setup.authority,
                "identity": {
                    "tenant_id": setup.authority.tenant_id,
                    "message_id": message_id,
                    "operation_id": sent.operation_id,
                },
                "attempt_id": attempt_id,
                "invocation_id": "delivery-invocation:" + attempt_id,
                "dispatch_id": result["dispatch_id"],
            },
            node,
            driver,
            adapter,
            private / "artifacts",
        )
        assert projected["disposition"] == "applied"
        assert query(
            setup, "SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
            "AND layer='response_received'", (message_id,),
        ) == [(1,)]
        assert query(
            setup, "SELECT count(*) FROM native_response_observations "
            "WHERE invocation_id=%s AND disposition='applied'",
            (projected["invocation_id"],),
        ) == [(1,)]
        stopped = host.stop_native()
        assert stopped["verified"] is True and stopped["remaining_pids"] == []
        read_kwargs = {
            "authority": setup.authority,
            "node": node,
            "driver": driver,
            "projection": projected,
            "artifact_root": private / "artifacts",
            "message_id": message_id,
            "operation_id": sent.operation_id,
            "attempt_id": attempt_id,
            "dispatch_id": result["dispatch_id"],
            "workflow_id": dispatcher.last["workflow_id"],
            "temporal_run_id": dispatcher.last["provider_run_id"],
            "temporal_endpoint": "127.0.0.1:7239",
            "temporal_namespace": os.environ["ACS_P1_TEMPORAL_NAMESPACE"],
            "os_proof": stopped,
            "expected_text": "synthetic final answer",
            "run_id": run_id,
            "source_commit": source_commit,
            "source_tree": source_tree,
        }
        lineage = read_original_opencode_scene(**read_kwargs)
        assert lineage["machine_id"] == lineage["pg"]["selection_machine_id"]
        assert lineage["node_id"] == lineage["pg"]["selection_node_id"]
        assert lineage["driver"]["prompt_async_count"] == 1
        with node._connect() as connection:
            connection.execute(
                "UPDATE mailbox SET command_id='changed' WHERE message_id=?", (message_id,)
            )
        with pytest.raises(OpenCodeReadbackRejected, match="persisted PG/Node"):
            read_original_opencode_scene(**read_kwargs)
        with node._connect() as connection:
            connection.execute(
                "UPDATE mailbox SET command_id=? WHERE message_id=?",
                (send.command_id, message_id),
            )
        with setup.authority._connect() as connection:
            connection.execute(
                "UPDATE delivery_attempts SET selection_json=jsonb_set("
                "selection_json,'{machine_id}',to_jsonb(%s::text)) WHERE message_id=%s",
                ("other-machine", message_id),
            )
        with pytest.raises(OpenCodeReadbackRejected, match="persisted PG/Node"):
            read_original_opencode_scene(**read_kwargs)
        driver.detach_transport()
    finally:
        if server is not None:
            server.close()
        if thread is not None:
            thread.join(timeout=1)
        supervisor.close()
        shutil.rmtree(private)
