"""No-model, same-Attempt Harness replacement probe for the P1 profile."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from runtime.artifacts import ArtifactError, LocalArtifactStore
from runtime.delivery_models import DeliveryEnvelope, InvocationObservation, InvocationRequest
from runtime.domain import DomainAuthority
from runtime.harness_sessions import BindingChange, BindingResult
from runtime.models import ArtifactRef
from runtime.node import NodeJournal
from runtime.recovery import (
    DriverCollectorAdapter,
    InvocationCollectionIdentity,
    NodeResponseOutbox,
    ProjectionDisposition,
)
from runtime.recovery_models import HarnessAttemptContext, HarnessSessionProof
from runtime.recovery_service import RecoveryService
from runtime.response_collector import NativeResponseCollector
from runtime.surface_config import trusted_local_node_response_reader

SCENARIO = "P1-HARNESS-REPLACEMENT"


class HarnessReplacementProbeError(RuntimeError):
    pass


class AcknowledgedFixtureDriver:
    """Commit one Invocation and ACK, leaving terminal response to collection."""

    evidence_class = "fixture_callback"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare(self, invocation: InvocationRequest) -> InvocationRequest:
        return invocation

    def invoke(self, invocation: InvocationRequest) -> InvocationObservation:
        self.calls.append(invocation.operation_id)
        return InvocationObservation(
            invocation_id=invocation.invocation_id,
            dispatch_id=invocation.dispatch_id,
            runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
            native_dispatch_ref="fixture-dispatch", native_ack_ref="fixture-ack",
        )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _command(command_factory, authority, name, kind, target, suffix, issued_at, *, revision=0,
             payload=None):
    command = command_factory(
        authority, name, kind, target, suffix, issued_at, revision=revision,
    )
    return command if payload is None else command.model_copy(update={"payload": payload})


class NoModelTerminalDriver:
    """Structured terminal fixture; invokes no Harness or model."""

    def __init__(self, identity, command_id: str, binding_id: str,
                 binding: dict[str, str | int], session_ref: str, turn_ref: str) -> None:
        self.identity = identity
        self.command_id = command_id
        self.binding_id = binding_id
        self.binding = binding
        self.session_ref = session_ref
        self.turn_ref = turn_ref
        self.calls: list[str] = []

    def invoke(self, *_args, **_kwargs):
        raise HarnessReplacementProbeError("no-model terminal fixture cannot invoke a Harness")

    def collect_result(self, _operation, operation_id: str) -> dict[str, Any]:
        if self.calls:
            raise HarnessReplacementProbeError("terminal fixture collected more than once")
        self.calls.append(operation_id)
        identity = self.identity
        return {
            "receipt_layer": "response_received",
            "operation_id": identity.operation_id,
            "command_id": self.command_id,
            "message_id": identity.message_id,
            "invocation_id": identity.invocation_id,
            "attempt_id": identity.attempt_id,
            "dispatch_id": identity.dispatch_id,
            "binding_id": self.binding_id,
            "binding": self.binding,
            "native_session_id": self.session_ref,
            "native_message_id": self.turn_ref,
            "native_terminal_outcome": "completed",
            "native_terminal_observed_at": datetime.now(UTC).isoformat(),
        }


def run(
    authority: DomainAuthority,
    node: NodeJournal,
    endpoint: Any,
    ledger: Any,
    work_id: str,
    message_id: str,
    delivery_operation_id: str,
    commit: str,
    tree: str,
    suffix: str,
    issued_at: datetime,
    *,
    register_execution: Callable[..., Any],
    domain_command: Callable[..., Any],
    private_json: Callable[[Path, dict[str, Any]], bytes],
) -> dict[str, Any]:
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    if proof_path.exists():
        prior = json.loads(proof_path.read_text(encoding="utf-8"))
        if (prior.get("message_id") != message_id
                or prior.get("delivery_operation_id") != delivery_operation_id):
            raise HarnessReplacementProbeError("Harness proof belongs to another delivery")
        return prior
    with authority._connect() as connection:
        rows = connection.execute(
            "SELECT m.envelope_json,a.invocation_json,a.selection_json,a.attempt_id "
            "FROM delivery_messages m JOIN delivery_attempts a "
            "ON a.tenant_id=m.tenant_id AND a.message_id=m.message_id "
            "WHERE m.tenant_id=%s AND m.message_id=%s AND a.status='delivered' "
            "ORDER BY a.ordinal",
            (authority.tenant_id, message_id),
        ).fetchall()
    if len(rows) != 1 or rows[0][1] is None:
        raise HarnessReplacementProbeError("Harness replacement requires one committed Invocation")
    envelope = DeliveryEnvelope.model_validate(rows[0][0])
    invocation = InvocationRequest.model_validate(rows[0][1])
    selected = rows[0][2]
    attempt_id = rows[0][3]
    if (invocation.attempt_id != attempt_id
            or invocation.message_id != message_id
            or invocation.operation_id != delivery_operation_id
            or envelope.packet.work_item_id != work_id
            or (envelope.packet.target_scope_id, envelope.packet.target_agent_slot_id)
            != ("local-scope", "local-slot")):
        raise HarnessReplacementProbeError("committed Delivery identity differs from WorkItem")
    owner, _observer, _signed = register_execution(
        authority, node, work_id, commit, tree, suffix + ":harness", issued_at,
        execution_attempt_id=attempt_id,
    )
    context = HarnessAttemptContext(
        work_item_id=work_id, scope_id="local-scope", agent_slot_id="local-slot",
        runtime_id=owner["runtime_id"], attempt_id=attempt_id,
        message_id=message_id, machine_id=node.machine_id, node_id=node.node_id,
        node_boot_incarnation=node.boot_incarnation, node_binding_revision=1,
        endpoint_id=envelope.endpoint_id,
        endpoint_binding_revision=envelope.binding_revision,
    )
    if (selected.get("machine_id"), selected.get("node_id"),
            selected.get("boot_incarnation"), selected.get("endpoint_id")) != (
            context.machine_id, context.node_id, context.node_boot_incarnation,
            context.endpoint_id,
    ):
        raise HarnessReplacementProbeError("Harness context differs from selected Node")
    binder = DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref="p1-harness-external:" + suffix,
        grant_ref="grant:p1-harness-external:" + suffix,
    ))
    binder.bootstrap_local_grant((
        "harness_session.manage", "harness_session.read",
        "harness_session.result", "work_item.read",
    ))
    old_id, new_id = "harness-old-" + suffix, "harness-new-" + suffix
    old_session, new_session = "ses-fixture-old-" + suffix, "ses-fixture-new-" + suffix
    old_change = BindingChange(
        binding_id=old_id, scope_id="local-scope", agent_slot_id="local-slot",
        driver_kind="opencode", native_session_ref=old_session,
        installed_version="fixture-no-model", receipt_ref="fixture:attach:" + suffix,
        attempt_context=context,
    )
    new_change = old_change.model_copy(update={
        "binding_id": new_id, "native_session_ref": new_session,
        "receipt_ref": "fixture:replace:" + suffix,
    })
    attach_command = _command(
        domain_command, binder, "harness_session.attach", "work_item", work_id,
        suffix + ":harness-attach", issued_at,
    )
    replace_command = _command(
        domain_command, binder, "harness_session.replace", "work_item", work_id,
        suffix + ":harness-replace", issued_at, revision=1,
    )
    attached = binder.harness_sessions.change(attach_command, old_change)
    replaced = binder.harness_sessions.change(replace_command, new_change)
    if attached.revision != 1 or replaced.revision != 2:
        raise HarnessReplacementProbeError("external binding revisions are incomplete")
    history = binder.harness_sessions.read(_command(
        domain_command, binder, "harness_session.read", "work_item", work_id,
        suffix + ":harness-read", issued_at, revision=2,
    ))
    if (history["active_binding_id"] != new_id
            or [(item["binding_id"], item["revision"], item["status"])
                for item in history["bindings"]]
            != [(old_id, 1, "retired"), (new_id, 2, "active")]
            or any(item["attempt_context"] != asdict(context)
                   for item in history["bindings"])):
        raise HarnessReplacementProbeError("replacement lost old binding provenance or Attempt identity")
    old_event = history["bindings"][0]["attached_event_id"]
    new_event = history["bindings"][1]["attached_event_id"]
    if not all(type(value) is int and value > 0 for value in (old_event, new_event)):
        raise HarnessReplacementProbeError("committed Harness binding events are unavailable")

    cas_root = ledger.root / f"{SCENARIO}-cas"
    with LocalArtifactStore(cas_root, "local-scope") as store:
        old_payload = _canonical({"session": old_session, "turn": "old-late", "state": "completed"})
        old_ref = store.put_bytes(old_payload, kind="output")
        with LocalArtifactStore(cas_root, "local-scope") as independent:
            if independent.read(old_ref) != old_payload:
                raise HarnessReplacementProbeError("old fixture result failed CAS readback")
        old_result = binder.harness_sessions.admit_result(_command(
            domain_command, binder, "harness_session.result", "work_item", work_id,
            suffix + ":old-late-result", issued_at, revision=2,
        ), BindingResult(
            result_id="harness-old-result-" + suffix, binding_id=old_id,
            native_session_ref=old_session, result_ref="artifact:" + old_ref.sha256,
        ))
        if old_result.state != "fenced_late":
            raise HarnessReplacementProbeError("retired Session result advanced the WorkItem")

        proof = HarnessSessionProof(
            binding_id=new_id, revision=2, driver_kind="opencode",
            native_session_ref=new_session, context=context,
            binding_event_id=new_event,
        )
        identity = NativeResponseCollector.dispatch_identity(invocation)
        driver_binding = {
            "node_id": context.node_id,
            "node_boot_id": context.node_boot_incarnation,
            "runtime_id": context.runtime_id,
            "attempt_id": context.attempt_id,
            "agent_slot_id": context.agent_slot_id,
            "revision": context.node_binding_revision,
        }
        collection = InvocationCollectionIdentity(
            dispatch=identity, command_id=envelope.command_id,
            binding_id="driver:" + new_id,
            binding_items=tuple(driver_binding.items()),
            driver_kind="opencode", native_session_ref=new_session,
            native_turn_ref="fixture-new-turn-" + suffix,
            harness_proof=proof,
        )
        driver = NoModelTerminalDriver(
            identity, envelope.command_id, collection.binding_id,
            driver_binding, new_session, collection.native_turn_ref,
        )
        stored_refs: list[ArtifactRef] = []

        def store_response(value: dict[str, Any]) -> tuple[str, str]:
            ref = store.put_bytes(_canonical(value), kind="output")
            stored_refs.append(ref)
            return "artifact:" + ref.sha256, ref.sha256

        outbox = node.response_outbox()
        observation = DriverCollectorAdapter(driver, outbox, store_response).collect(
            object(), identity.operation_id, collection,
        )
        if driver.calls != [delivery_operation_id] or len(stored_refs) != 1:
            raise HarnessReplacementProbeError("no-model Driver terminal was not collected once")
        with node._transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS p1_harness_terminal_calls("
                "invocation_id TEXT PRIMARY KEY,projection_id TEXT NOT NULL,"
                "native_session_ref TEXT NOT NULL,operation_id TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO p1_harness_terminal_calls VALUES (?,?,?,?)",
                (identity.invocation_id, observation.projection_id,
                 new_session, delivery_operation_id),
            )
        new_ref = stored_refs[0]
        if outbox.by_invocation(identity) != observation:
            raise HarnessReplacementProbeError("Node terminal response was not durably read back")
        new_result = binder.harness_sessions.admit_result(_command(
            domain_command, binder, "harness_session.result", "work_item", work_id,
            suffix + ":new-current-result", issued_at, revision=2,
        ), BindingResult(
            result_id="harness-new-result-" + suffix, binding_id=new_id,
            native_session_ref=new_session, result_ref="artifact:" + new_ref.sha256,
        ))
        if new_result.state != "current":
            raise HarnessReplacementProbeError("new Session result was not current")

        projector = DomainAuthority(authority._dsn, context=replace(
            authority.context,
            principal_ref="p1-harness-projector:" + suffix,
            grant_ref="grant:p1-harness-projector:" + suffix,
        ), node_response_reader=trusted_local_node_response_reader({
            envelope.endpoint_id: endpoint,
        }))
        projector.bootstrap_local_grant((
            "delivery.project", "delivery.read", "delivery.consume", "work_item.read",
        ))
        payload = {"observation": observation.canonical()}
        projected = RecoveryService(projector).execute(_command(
            domain_command, projector, "delivery.project_native_response",
            "projection", observation.projection_id,
            suffix + ":project-new-response", issued_at, payload=payload,
        ), "delivery.project_native_response", payload)
        if projected.state != "applied":
            raise HarnessReplacementProbeError("current Session terminal did not project")
        outbox.mark(ProjectionDisposition(
            observation.projection_id,
            NodeResponseOutbox._payload(observation)[1], projected.state,
        ))
        if outbox.recover() != ():
            raise HarnessReplacementProbeError("Node projection outbox still has pending work")
        status_payload = {"projection_id": observation.projection_id, "scope_id": "local-scope"}
        status = RecoveryService(projector).execute(_command(
            domain_command, projector, "delivery.projection.status", "projection",
            observation.projection_id, suffix + ":projection-read", issued_at,
            payload=status_payload,
        ), "delivery.projection.status", status_payload)
        if (status["disposition"] != "applied"
                or status["harness_proof"]["binding_id"] != new_id):
            raise HarnessReplacementProbeError("projected response readback lost current Session proof")
        with LocalArtifactStore(cas_root, "local-scope") as independent:
            if (_sha(independent.read(old_ref)) != old_ref.sha256
                    or _sha(independent.read(new_ref)) != new_ref.sha256):
                raise HarnessReplacementProbeError("Session result CAS readback changed")

    with authority._connect() as connection:
        work = connection.execute(
            "SELECT scope_id,agent_slot_id,state,revision FROM work_items WHERE work_item_id=%s",
            (work_id,),
        ).fetchone()
        admissions = connection.execute(
            "SELECT binding_id,disposition FROM harness_session_result_admissions "
            "WHERE work_item_id=%s ORDER BY result_id",
            (work_id,),
        ).fetchall()
        response_receipts = connection.execute(
            "SELECT attempt_id,dispatch_id,receipt_id FROM delivery_receipts "
            "WHERE message_id=%s AND layer='response_received'",
            (message_id,),
        ).fetchall()
        responses = connection.execute(
            "SELECT projection_id,disposition,harness_proof->>'binding_id' "
            "FROM native_response_observations WHERE message_id=%s",
            (message_id,),
        ).fetchall()
        accepted = connection.execute(
            "SELECT count(*) FROM accepted_state_revisions WHERE work_item_id=%s",
            (work_id,),
        ).fetchone()[0]
    if (work != ("local-scope", "local-slot", "candidate", 0)
            or admissions != [(new_id, "current"), (old_id, "fenced_late")]
            or response_receipts != [(
                attempt_id, invocation.dispatch_id, observation.receipt_id,
            )]
            or responses != [(observation.projection_id, "applied", new_id)]
            or accepted != 0):
        raise HarnessReplacementProbeError("Domain admitted a stale or duplicate native response")
    value = {
        "work_item_id": work_id, "message_id": message_id,
        "delivery_operation_id": delivery_operation_id,
        "attempt_id": attempt_id, "dispatch_id": invocation.dispatch_id,
        "invocation_id": invocation.invocation_id,
        "source_commit": commit, "source_tree": tree,
        "machine_id": node.machine_id, "node_id": node.node_id,
        "runtime_id": context.runtime_id,
        "old_binding_id": old_id, "new_binding_id": new_id,
        "old_native_session_ref": old_session,
        "new_native_session_ref": new_session,
        "old_binding_event_id": old_event,
        "new_binding_event_id": new_event,
        "old_result_disposition": old_result.state,
        "new_result_disposition": new_result.state,
        "old_result_ref": old_ref.model_dump(mode="json"),
        "new_result_ref": new_ref.model_dump(mode="json"),
        "projection_id": observation.projection_id,
        "response_receipt_id": observation.receipt_id,
        "node_observation_digest": NodeResponseOutbox._payload(observation)[1],
        "driver_calls": driver.calls,
        "head_revision": 2,
        "response_received_count": 1,
        "accepted_revision_count": 0,
        "no_model_calls": True,
    }
    private_json(proof_path, value)
    return value


def read_layer(profile: dict[str, Any], kind: str, ledger: Any,
               row: dict[str, Any], lineage: dict[str, Any]) -> dict[str, Any]:
    proof = lineage.get("harness_replacement_proof")
    if not isinstance(proof, dict):
        raise HarnessReplacementProbeError("Harness replacement proof is missing")
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    try:
        raw = proof_path.read_bytes()
        stored = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise HarnessReplacementProbeError("Harness replacement proof is unreadable") from exc
    if (stored != proof or raw != _canonical(proof)
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("attempt_id") != lineage["attempt_id"]
            or proof.get("dispatch_id") != lineage["dispatch_id"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("old_result_disposition") != "fenced_late"
            or proof.get("new_result_disposition") != "current"
            or proof.get("head_revision") != 2
            or proof.get("response_received_count") != 1
            or proof.get("accepted_revision_count") != 0
            or proof.get("no_model_calls") is not True):
        raise HarnessReplacementProbeError("Harness replacement proof differs from Runtime lineage")
    if kind == "postgresql":
        scoped = make_conninfo(profile["postgres_dsn"],
                               options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            work = connection.execute(
                "SELECT scope_id,agent_slot_id,state,revision FROM work_items WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()
            head = connection.execute(
                "SELECT revision,active_binding_id FROM harness_session_heads WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()
            bindings = connection.execute(
                "SELECT binding_id,revision,status,attempt_context,attached_event_id "
                "FROM harness_session_bindings WHERE work_item_id=%s ORDER BY revision",
                (proof["work_item_id"],),
            ).fetchall()
            admissions = connection.execute(
                "SELECT binding_id,disposition FROM harness_session_result_admissions "
                "WHERE work_item_id=%s ORDER BY result_id",
                (proof["work_item_id"],),
            ).fetchall()
            receipts = connection.execute(
                "SELECT attempt_id,dispatch_id,receipt_id FROM delivery_receipts "
                "WHERE message_id=%s AND layer='response_received'",
                (proof["message_id"],),
            ).fetchall()
            response = connection.execute(
                "SELECT disposition,harness_proof->>'binding_id' FROM native_response_observations "
                "WHERE projection_id=%s", (proof["projection_id"],),
            ).fetchone()
            accepted = connection.execute(
                "SELECT count(*) FROM accepted_state_revisions WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()[0]
        if (work != ("local-scope", "local-slot", "candidate", 0)
                or head != (2, proof["new_binding_id"])
                or len(bindings) != 2
                or [(item[0], item[1], item[2], item[4]) for item in bindings] != [
                    (proof["old_binding_id"], 1, "retired", proof["old_binding_event_id"]),
                    (proof["new_binding_id"], 2, "active", proof["new_binding_event_id"]),
                ]
                or bindings[0][3] != bindings[1][3]
                or admissions != [(proof["new_binding_id"], "current"),
                                  (proof["old_binding_id"], "fenced_late")]
                or receipts != [(proof["attempt_id"], proof["dispatch_id"],
                                 proof["response_receipt_id"])]
                or response != ("applied", proof["new_binding_id"])
                or accepted != 0):
            raise HarnessReplacementProbeError("PostgreSQL Harness replacement lineage changed")
        return {"historical_bindings": 2, "late_fenced": True,
                "response_received_count": 1, "accepted_unchanged": True}
    if kind == "sqlite":
        node_path = ledger.root / lineage["node_journal"]
        with sqlite3.connect(node_path) as connection:
            response = connection.execute(
                "SELECT state,canonical_digest FROM native_response_observations "
                "WHERE projection_id=?", (proof["projection_id"],),
            ).fetchone()
            other = connection.execute(
                "SELECT count(*) FROM native_response_observations WHERE tenant_id=?",
                (lineage["tenant_id"],),
            ).fetchone()[0]
            terminal = connection.execute(
                "SELECT invocation_id,projection_id,native_session_ref,operation_id "
                "FROM p1_harness_terminal_calls",
            ).fetchall()
        if (response != ("applied", proof["node_observation_digest"]) or other != 1
                or terminal != [(
                    proof["invocation_id"], proof["projection_id"],
                    proof["new_native_session_ref"], proof["delivery_operation_id"],
                )]):
            raise HarnessReplacementProbeError("Node response Outbox changed")
        return {"node_terminal_count": 1, "node_projection_applied": True}
    if kind in {"driver", "os"}:
        cas_root = ledger.root / f"{SCENARIO}-cas"
        refs = [ArtifactRef.model_validate(proof[key], strict=True)
                for key in ("old_result_ref", "new_result_ref")]
        with LocalArtifactStore(cas_root, "local-scope") as store:
            try:
                if any(_sha(store.read(ref)) != ref.sha256 for ref in refs):
                    raise HarnessReplacementProbeError("Session fixture CAS result changed")
            except ArtifactError as exc:
                raise HarnessReplacementProbeError("Session fixture CAS result changed") from exc
        if proof["driver_calls"] != [proof["delivery_operation_id"]]:
            raise HarnessReplacementProbeError("no-model Driver collection count changed")
        return {"fixture_terminal_collected_once": True, "session_result_cas_readback": True,
                "model_calls": 0}
    return {"harness_proof_readback": True}
