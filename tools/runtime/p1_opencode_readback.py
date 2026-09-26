"""Fresh cross-authority readback for one original OpenCode delivery attempt."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from temporalio.client import Client

from runtime.node import NodeJournal
from runtime.opencode_driver import OpenCodeNativeDriver


class OpenCodeReadbackRejected(ValueError):
    pass


def validate_opencode_lineage(value: object) -> dict[str, Any]:
    required = {
        "run_id", "source_commit", "source_tree", "machine_id", "node_id",
        "command_id", "message_id", "operation_id", "attempt_id", "dispatch_id",
        "invocation_id", "native_session_id", "native_message_id",
        "native_assistant_ids", "pg", "node", "temporal", "driver", "response", "os",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise OpenCodeReadbackRejected("OpenCode cross-authority shape differs")
    for name in required - {"pg", "node", "temporal", "driver", "response", "os", "native_assistant_ids"}:
        if not isinstance(value[name], str) or not value[name]:
            raise OpenCodeReadbackRejected("OpenCode identity is incomplete")
    if not all(re.fullmatch(r"[a-f0-9]{40}", value[name]) for name in ("source_commit", "source_tree")):
        raise OpenCodeReadbackRejected("OpenCode source object differs")
    if (
        value["invocation_id"] != "delivery-invocation:" + value["attempt_id"]
        or value["dispatch_id"] != "delivery-dispatch:" + value["attempt_id"]
        or not isinstance(value["native_assistant_ids"], list)
        or not value["native_assistant_ids"]
        or not re.fullmatch(r"ses_[A-Za-z0-9_-]{1,250}", value["native_session_id"])
        or not re.fullmatch(r"msg_[A-Za-z0-9_-]{1,250}", value["native_message_id"])
        or any(
            not isinstance(identifier, str)
            or not re.fullmatch(r"msg_[A-Za-z0-9_-]{1,250}", identifier)
            for identifier in value["native_assistant_ids"]
        )
        or len(set(value["native_assistant_ids"])) != len(value["native_assistant_ids"])
    ):
        raise OpenCodeReadbackRejected("OpenCode original attempt/native identity differs")
    identity = [
        value["message_id"], value["operation_id"], value["attempt_id"],
        value["invocation_id"], value["dispatch_id"],
    ]
    pg, node, temporal = value["pg"], value["node"], value["temporal"]
    driver, response, system = value["driver"], value["response"], value["os"]
    if any(not isinstance(layer, dict) for layer in (pg, node, temporal, driver, response, system)):
        raise OpenCodeReadbackRejected("OpenCode required authority layer is missing")
    if (
        pg.get("identity") != identity
        or pg.get("selection_machine_id") != value["machine_id"]
        or pg.get("selection_node_id") != value["node_id"]
        or any(type(pg.get(name)) is not int or pg[name] != 1 for name in (
            "attempt_count", "dispatch_marker_count", "event_count", "outbox_count",
            "response_projection_count", "response_receipt_count",
        ))
    ):
        raise OpenCodeReadbackRejected("OpenCode PG selection or projection differs")
    if (
        node.get("identity") != identity
        or node.get("machine_id") != value["machine_id"]
        or node.get("node_id") != value["node_id"]
        or any(type(node.get(name)) is not int or node[name] != 1 for name in (
            "mailbox_count", "invocation_count", "response_outbox_count",
        ))
    ):
        raise OpenCodeReadbackRejected("OpenCode Node journal differs from PG attempt")
    if (
        temporal.get("workflow_id") != "acs-delivery/" + value["operation_id"]
        or not isinstance(temporal.get("run_id"), str)
        or not temporal["run_id"]
        or temporal.get("status") != "delivered"
    ):
        raise OpenCodeReadbackRejected("OpenCode original Temporal Workflow/Run differs")
    if (
        driver.get("invocation_id") != value["invocation_id"]
        or driver.get("session_id") != value["native_session_id"]
        or driver.get("message_id") != value["native_message_id"]
        or driver.get("assistant_ids") != value["native_assistant_ids"]
        or type(driver.get("prompt_async_count")) is not int
        or driver["prompt_async_count"] != 1
        or driver.get("terminal_status") != "completed"
        or driver.get("assistant_text_exact") is not True
    ):
        raise OpenCodeReadbackRejected("OpenCode Driver lacks one exact native terminal")
    auth = driver.get("auth")
    if auth is not None and (
        not isinstance(auth, dict)
        or set(auth) != {
            "storage", "provider_id", "owner_mode", "same_reference",
            "provider_connected", "native_route_equal", "native_source",
        }
        or auth["storage"] != "xdg-data-auth-json"
        or auth["owner_mode"] != "0600"
        or auth["same_reference"] is not True
        or auth["provider_connected"] is not True
        or auth["native_route_equal"] is not True
        or auth["native_source"] not in {"api", "config"}
    ):
        raise OpenCodeReadbackRejected("OpenCode native owner auth readback differs")
    if (
        response.get("invocation_id") != value["invocation_id"]
        or response.get("disposition") != "applied"
        or response.get("artifact_readback") is not True
        or response.get("digest_match") is not True
        or not isinstance(response.get("response_digest"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", response["response_digest"])
        or not isinstance(response.get("projection_id"), str)
        or not response["projection_id"].startswith("projection:")
    ):
        raise OpenCodeReadbackRejected("OpenCode artifact or Domain projection differs")
    if (
        system.get("verified") is not True
        or system.get("remaining_pids") != []
        or system.get("root_exited") is not True
        or system.get("wrapper_exited") is not True
        or not isinstance(system.get("unit"), str)
        or value["run_id"] not in system.get("unit", "")
    ):
        raise OpenCodeReadbackRejected("OpenCode Systemd containment remains uncertain")
    return value


def read_original_opencode_scene(
    *,
    authority: Any,
    node: NodeJournal,
    driver: OpenCodeNativeDriver,
    projection: dict[str, Any],
    artifact_root: Path,
    message_id: str,
    operation_id: str,
    attempt_id: str,
    dispatch_id: str,
    workflow_id: str,
    temporal_run_id: str,
    temporal_endpoint: str,
    temporal_namespace: str,
    os_proof: dict[str, Any],
    expected_text: str,
    run_id: str,
    source_commit: str,
    source_tree: str,
    auth_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    invocation_id = "delivery-invocation:" + attempt_id
    with authority._connect() as connection:
        message = connection.execute(
            "SELECT command_id,state,receipt_high_water FROM delivery_messages "
            "WHERE message_id=%s AND operation_id=%s", (message_id, operation_id),
        ).fetchone()
        if message is None:
            raise OpenCodeReadbackRejected("OpenCode original Domain message disappeared")
        attempts = connection.execute(
            "SELECT attempt_id,dispatch_id,status,selection_json->>'machine_id',"
            "selection_json->>'node_id',invocation_json->>'invocation_id' "
            "FROM delivery_attempts WHERE message_id=%s ORDER BY ordinal",
            (message_id,),
        ).fetchall()
        markers = connection.execute(
            "SELECT attempt_id,dispatch_id FROM delivery_receipts WHERE message_id=%s "
            "AND layer='runtime_dispatched'", (message_id,),
        ).fetchall()
        responses = connection.execute(
            "SELECT attempt_id,dispatch_id FROM delivery_receipts WHERE message_id=%s "
            "AND layer='response_received'", (message_id,),
        ).fetchall()
        projections = connection.execute(
            "SELECT projection_id,invocation_id,attempt_id,dispatch_id,response_digest,"
            "disposition FROM native_response_observations WHERE message_id=%s",
            (message_id,),
        ).fetchall()
        counts = [
            connection.execute(statement, params).fetchone()[0]
            for statement, params in (
                ("SELECT count(*) FROM delivery_attempts WHERE message_id=%s", (message_id,)),
                (("SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
                  "AND layer='runtime_dispatched'"), (message_id,)),
                ("SELECT count(*) FROM domain_events WHERE command_id=%s", (message[0],)),
                ("SELECT count(*) FROM outbox WHERE operation_id=%s", (operation_id,)),
                (("SELECT count(*) FROM native_response_observations WHERE invocation_id=%s "
                  "AND disposition='applied'"), (invocation_id,)),
                (("SELECT count(*) FROM delivery_receipts WHERE message_id=%s "
                  "AND layer='response_received'"), (message_id,)),
            )
        ]
    with node._connect() as connection:
        mailbox = connection.execute(
            "SELECT command_id,operation_id FROM mailbox WHERE message_id=?",
            (message_id,),
        ).fetchall()
        invocations = connection.execute(
            "SELECT dispatch_id,state FROM delivery_invocations WHERE invocation_id=?",
            (invocation_id,),
        ).fetchall()
        response_outbox = connection.execute(
            "SELECT projection_id,state FROM native_response_observations "
            "WHERE invocation_id=?", (invocation_id,),
        ).fetchall()
        mailbox = [tuple(row) for row in mailbox]
        invocations = [tuple(row) for row in invocations]
        response_outbox = [tuple(row) for row in response_outbox]
        node_counts = [
            connection.execute(statement, params).fetchone()[0]
            for statement, params in (
                ("SELECT count(*) FROM mailbox WHERE message_id=?", (message_id,)),
                ("SELECT count(*) FROM delivery_invocations WHERE invocation_id=?", (invocation_id,)),
                (("SELECT count(*) FROM native_response_observations WHERE invocation_id=? "
                  "AND state='applied'"), (invocation_id,)),
            )
        ]
    with driver.journal._connect() as connection:
        rows = connection.execute(
            "SELECT kind,body FROM driver_events WHERE operation_id=? ORDER BY sequence",
            (invocation_id,),
        ).fetchall()
        auth_rows = connection.execute(
            "SELECT body FROM driver_events WHERE operation_id=? "
            "AND kind='provider_auth_readback' ORDER BY sequence",
            (run_id + "-spawn",),
        ).fetchall() if auth_observation is not None else []
    if auth_observation is not None and (
        len(auth_rows) != 1 or json.loads(auth_rows[0][0]) != auth_observation
    ):
        raise OpenCodeReadbackRejected("OpenCode native auth readback journal differs")
    events = [(kind, json.loads(body)) for kind, body in rows]
    prompts = [body for kind, body in events if kind == "http_dispatch"
               and body.get("path", "").endswith("/prompt_async")]
    terminals = [body for kind, body in events if kind == "terminal_readback"]
    invoked = driver.journal.read(invocation_id)
    if invoked is None or not terminals:
        raise OpenCodeReadbackRejected("OpenCode original native terminal disappeared")
    receipt = terminals[-1]
    if (
        invoked["state"] != "acknowledged"
        or not isinstance(invoked.get("result"), dict)
        or invoked["input"]["command_id"] != message[0]
        or invoked["input"]["message_id"] != message_id
        or invoked["result"].get("native_message_id") != receipt.get("native_message_id")
        or mailbox != [(message[0], operation_id)]
        or invocations != [(dispatch_id, "acknowledged")]
        or response_outbox != [(projection["projection_id"], "applied")]
        or attempts != [(
            attempt_id, dispatch_id, "delivered", node.machine_id, node.node_id,
            invocation_id,
        )]
        or markers != [(attempt_id, dispatch_id)]
        or responses != [(attempt_id, dispatch_id)]
        or projections != [(
            projection["projection_id"], invocation_id, attempt_id, dispatch_id,
            projection["response_digest"], "applied",
        )]
    ):
        raise OpenCodeReadbackRejected("OpenCode persisted PG/Node/Driver lineage differs")

    async def temporal_readback():
        client = await Client.connect(temporal_endpoint, namespace=temporal_namespace)
        result = await client.get_workflow_handle(workflow_id, run_id=temporal_run_id).result()
        return result.get("status") if isinstance(result, dict) else None

    provider_status = asyncio.run(temporal_readback())
    artifact_sha = projection["response_artifact_ref"].removeprefix("artifact:")
    artifact = artifact_root / artifact_sha[:2] / artifact_sha
    artifact_ok = artifact.is_file() and hashlib.sha256(artifact.read_bytes()).hexdigest() == artifact_sha
    identity = [message_id, operation_id, attempt_id, invocation_id, dispatch_id]
    value = {
        "run_id": run_id,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "machine_id": node.machine_id,
        "node_id": node.node_id,
        "command_id": message[0],
        "message_id": message_id,
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "dispatch_id": dispatch_id,
        "invocation_id": invocation_id,
        "native_session_id": receipt.get("native_session_id"),
        "native_message_id": receipt.get("native_message_id"),
        "native_assistant_ids": receipt.get("native_assistant_ids"),
        "pg": {
            "identity": identity,
            "selection_machine_id": attempts[0][3],
            "selection_node_id": attempts[0][4],
            "attempt_count": counts[0], "dispatch_marker_count": counts[1],
            "event_count": counts[2], "outbox_count": counts[3],
            "response_projection_count": counts[4], "response_receipt_count": counts[5],
        },
        "node": {
            "identity": identity, "machine_id": node.machine_id, "node_id": node.node_id,
            "mailbox_count": node_counts[0], "invocation_count": node_counts[1],
            "response_outbox_count": node_counts[2],
        },
        "temporal": {"workflow_id": workflow_id, "run_id": temporal_run_id,
                     "status": provider_status},
        "driver": {
            "invocation_id": invocation_id,
            "session_id": receipt.get("native_session_id"),
            "message_id": receipt.get("native_message_id"),
            "assistant_ids": receipt.get("native_assistant_ids"),
            "prompt_async_count": len(prompts),
            "terminal_status": receipt.get("native_terminal_outcome"),
            "assistant_text_exact": receipt.get("assistant_text") == [expected_text],
            "terminal_sha256": hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            **({"auth": auth_observation} if auth_observation is not None else {}),
        },
        "response": {
            "invocation_id": projection["invocation_id"],
            "disposition": projection["disposition"],
            "artifact_readback": artifact_ok,
            "digest_match": projection["response_digest"] == artifact_sha,
            "response_digest": projection["response_digest"],
            "projection_id": projection["projection_id"],
        },
        "os": os_proof,
    }
    if message[1:] != ("delivered", "response_received"):
        raise OpenCodeReadbackRejected("OpenCode Domain response high water is incomplete")
    return validate_opencode_lineage(value)
