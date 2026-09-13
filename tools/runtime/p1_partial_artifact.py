"""Same-lineage partial CAS publication probe for the P1 profile runner."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo

from runtime.artifacts import ArtifactError, LocalArtifactStore
from runtime.domain import DomainAuthority
from runtime.errors import AcceptanceGuardFailed, InvalidTransition
from runtime.models import ArtifactRef, ExecutionReceipt, TransitionRequest, WorkItemState
from runtime.node import NodeJournal

SCENARIO = "P1-PARTIAL-ARTIFACT"


class PartialArtifactProbeError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def inject_partial_output(store: LocalArtifactStore, payload: bytes) -> dict[str, Any]:
    """Force a real prefix write and EIO inside the production CAS publisher."""
    if len(payload) < 9:
        raise PartialArtifactProbeError("partial output payload is too short")
    original_open, original_write = os.open, os.write
    original_unlink, original_fsync = os.unlink, os.fsync
    observed: dict[str, Any] = {
        "fd": None, "written": 0, "faulted": False,
        "unlinked": False, "parent_fd": None, "cleanup_fsynced": False,
    }
    issued_ref: ArtifactRef | None = None

    def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.startswith(".artifact-"):
            if observed["fd"] is not None:
                raise PartialArtifactProbeError("multiple CAS temporary files opened")
            observed["fd"] = descriptor
        return descriptor

    def interrupted_write(descriptor, data):
        if descriptor == observed["fd"]:
            if observed["written"] == 0:
                count = original_write(descriptor, data[:7])
                observed["written"] = count
                return count
            observed["faulted"] = True
            raise OSError(errno.EIO, "injected partial CAS write")
        return original_write(descriptor, data)

    def tracked_unlink(path, *, dir_fd=None):
        result = original_unlink(path, dir_fd=dir_fd)
        if isinstance(path, str) and path.startswith(".artifact-"):
            observed["unlinked"] = True
            observed["parent_fd"] = dir_fd
        return result

    def tracked_fsync(descriptor):
        result = original_fsync(descriptor)
        if observed["unlinked"] and descriptor == observed["parent_fd"]:
            observed["cleanup_fsynced"] = True
        return result

    try:
        with (patch.object(os, "open", tracked_open),
              patch.object(os, "write", interrupted_write),
              patch.object(os, "unlink", tracked_unlink),
              patch.object(os, "fsync", tracked_fsync)):
            issued_ref = store.put_bytes(payload, kind="output")
    except OSError as exc:
        if exc.errno != errno.EIO or not observed["faulted"]:
            raise PartialArtifactProbeError("CAS failed before the intended partial write") from exc
    if issued_ref is not None or not 0 < observed["written"] < len(payload):
        raise PartialArtifactProbeError("partial CAS write unexpectedly issued a complete reference")
    if not observed["unlinked"] or not observed["cleanup_fsynced"]:
        raise PartialArtifactProbeError("partial CAS temporary cleanup was not durably synced")

    digest = _sha(payload)
    expected_path = f"{digest[:2]}/{digest}"
    expected_ref = ArtifactRef(
        path=expected_path, sha256=digest, size_bytes=len(payload),
        media_type="application/octet-stream", kind="output",
        scope_id=store.scope_id, immutable=True,
    )
    try:
        store.verify(expected_ref)
    except ArtifactError:
        pass
    else:
        raise PartialArtifactProbeError("partial output can be verified as a complete artifact")
    if (store.root / expected_path).exists() or list(store.root.rglob(".artifact-*")):
        raise PartialArtifactProbeError("partial CAS object or temporary file survived cleanup")
    return {
        "partial_bytes_written": observed["written"],
        "expected_output_sha256": digest,
        "expected_output_path": expected_path,
        "expected_output_size": len(payload),
        "no_ref_issued": True,
        "temporary_files_cleaned": True,
        "cleanup_directory_fsynced": True,
    }


def run(
    authority: DomainAuthority,
    node: NodeJournal,
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
        previous = json.loads(proof_path.read_text(encoding="utf-8"))
        if (previous.get("delivery_operation_id") != delivery_operation_id
                or previous.get("message_id") != message_id):
            raise PartialArtifactProbeError("partial artifact proof belongs to another delivery")
        return previous
    with authority._connect() as connection:
        attempts = connection.execute(
            "SELECT attempt_id,dispatch_id,status FROM delivery_attempts "
            "WHERE message_id=%s ORDER BY ordinal", (message_id,),
        ).fetchall()
    if len(attempts) != 1 or attempts[0][2] != "delivered":
        raise PartialArtifactProbeError("partial artifact requires one delivered Attempt")
    attempt_id, dispatch_id, _status = attempts[0]
    cas_root = ledger.root / f"{SCENARIO}-cas"
    payload = ("P1 partial output for " + delivery_operation_id).encode()
    with LocalArtifactStore(cas_root, "local-scope") as store:
        producer = DomainAuthority(
            authority._dsn, context=authority.context, artifact_store=store,
        )
        producer.bootstrap_local_grant((
            "work_item.create", "delivery.manage", "message.send", "message.read",
            "runtime.invoke", "execution.record", "evidence.record", "work_item.read",
        ))
        owner, observer, signed = register_execution(
            producer, node, work_id, commit, tree, suffix + ":partial", issued_at,
            execution_attempt_id=attempt_id, artifact_store=store,
        )
        binding = owner["execution_binding"]
        if (binding["attempt_id"] != attempt_id
                or binding["work_item_id"] != work_id
                or binding["source_commit"] != commit
                or binding["source_tree"] != tree):
            raise PartialArtifactProbeError("partial output execution differs from Delivery Attempt")

        control_payload = ("complete readback for " + delivery_operation_id).encode()
        control_ref = store.put_bytes(control_payload, kind="readback")
        with LocalArtifactStore(cas_root, "local-scope") as independent:
            if independent.read(control_ref) != control_payload:
                raise PartialArtifactProbeError("complete control artifact failed independent readback")
        fault = inject_partial_output(store, payload)
        expected_ref = ArtifactRef(
            path=fault["expected_output_path"],
            sha256=fault["expected_output_sha256"],
            size_bytes=fault["expected_output_size"],
            media_type="application/octet-stream", kind="output",
            scope_id="local-scope", immutable=True,
        )
        receipt = ExecutionReceipt(
            receipt_id="partial-execution-receipt-" + suffix,
            work_item_id=work_id, attempt_id=attempt_id,
            runtime_id=owner["runtime_id"], provider=binding["provider"],
            command_id=binding["execution_command_id"],
            operation_id=binding["execution_operation_id"],
            event_id=binding["execution_event_id"],
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            source_commit=commit, source_tree=tree,
            test_commands=("P1 partial output fixture",),
            test_exit_codes=(0,), test_exit_code=0,
            os="linux", toolchain="P1 partial CAS fault fixture",
            artifact_refs=(expected_ref,), readback_refs=(control_ref,),
            source_sync="committed-private-probe-source",
            status="succeeded", observed_at=datetime.now(UTC),
        )
        receipt_command = domain_command(
            observer, "execution.record", "work_item", work_id,
            suffix + ":partial-receipt", issued_at,
        )
        try:
            observer.record_execution_receipt(
                receipt_command, receipt,
                node_proof=signed(receipt_command, receipt, "receipt"),
            )
        except AcceptanceGuardFailed as exc:
            if "artifact bytes are not verified" not in str(exc):
                raise PartialArtifactProbeError("receipt failed for a reason other than partial CAS") from exc
        else:
            raise PartialArtifactProbeError("Domain accepted an unverified partial output receipt")

        finalizer = DomainAuthority(authority._dsn, context=replace(
            authority.context,
            principal_ref="p1-partial-finalizer:" + suffix,
            grant_ref="grant:p1-partial-finalizer:" + suffix,
        ), artifact_store=store)
        finalizer.bootstrap_local_grant((
            "work_item.transition", "acceptance.finalize", "work_item.read",
        ))
        transition = TransitionRequest(
            to_state=WorkItemState.ACCEPTANCE_READY,
            evidence_refs=("partial-evidence-" + suffix,),
            review_ref="partial-review-" + suffix,
        )
        try:
            finalizer.transition_work_item(domain_command(
                finalizer, "work_item.transition", "work_item", work_id,
                suffix + ":partial-ready", issued_at,
            ), transition)
        except AcceptanceGuardFailed as exc:
            if "complete evidence bundle set is missing" not in str(exc):
                raise PartialArtifactProbeError("readiness failed for an unrelated reason") from exc
        else:
            raise PartialArtifactProbeError("Finalizer made a partial artifact acceptance-ready")
        try:
            finalizer.transition_work_item(domain_command(
                finalizer, "work_item.transition", "work_item", work_id,
                suffix + ":partial-accept", issued_at,
            ), TransitionRequest(
                to_state=WorkItemState.ACCEPTED,
                evidence_refs=("partial-evidence-" + suffix,),
                review_ref="partial-review-" + suffix,
            ))
        except InvalidTransition:
            pass
        else:
            raise PartialArtifactProbeError("Finalizer accepted a partial artifact")

    with authority._connect() as connection:
        work = connection.execute(
            "SELECT state,revision FROM work_items WHERE work_item_id=%s", (work_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM execution_receipts WHERE work_item_id=%s", (work_id,),
        ).fetchone()[0]
        accepted_count = connection.execute(
            "SELECT count(*) FROM accepted_state_revisions WHERE work_item_id=%s", (work_id,),
        ).fetchone()[0]
        evidence_count = connection.execute(
            "SELECT count(*) FROM evidence WHERE work_item_id=%s", (work_id,),
        ).fetchone()[0]
        receipt_dedup = connection.execute(
            "SELECT count(*) FROM command_dedup WHERE command_id=%s",
            (receipt_command.command_id,),
        ).fetchone()[0]
        receipt_events = connection.execute(
            "SELECT count(*) FROM domain_events WHERE command_id=%s",
            (receipt_command.command_id,),
        ).fetchone()[0]
    if (work != ("candidate", 0) or any((receipt_count, accepted_count,
                                          evidence_count, receipt_dedup, receipt_events))):
        raise PartialArtifactProbeError("partial output left accepting Domain state")

    proof = {
        "work_item_id": work_id,
        "message_id": message_id,
        "delivery_operation_id": delivery_operation_id,
        "attempt_id": attempt_id,
        "dispatch_id": dispatch_id,
        "source_commit": commit,
        "source_tree": tree,
        "machine_id": node.machine_id,
        "node_id": node.node_id,
        "runtime_id": owner["runtime_id"],
        "receipt_command_id": receipt_command.command_id,
        "candidate_ref": binding["candidate_ref"],
        "control_ref": control_ref.model_dump(mode="json"),
        "control_sha256": _sha(control_payload),
        "receipt_rejected_for_partial_cas": True,
        "finalizer_ready_rejected": True,
        "finalizer_accept_rejected": True,
        "domain_work_state": "candidate",
        "domain_work_revision": 0,
        **fault,
    }
    private_json(proof_path, proof)
    return proof


def read_layer(
    profile: dict[str, Any], kind: str, ledger: Any,
    row: dict[str, Any], lineage: dict[str, Any],
) -> dict[str, Any]:
    proof = lineage.get("partial_artifact_proof")
    if not isinstance(proof, dict):
        raise PartialArtifactProbeError("partial artifact proof is missing")
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    try:
        proof_bytes = proof_path.read_bytes()
        stored = json.loads(proof_bytes)
    except (OSError, ValueError) as exc:
        raise PartialArtifactProbeError("partial artifact proof is unreadable") from exc
    if (stored != proof or proof_bytes != _canonical(proof)
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("attempt_id") != lineage["attempt_id"]
            or proof.get("dispatch_id") != lineage["dispatch_id"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("receipt_rejected_for_partial_cas") is not True
            or proof.get("finalizer_ready_rejected") is not True
            or proof.get("finalizer_accept_rejected") is not True
            or proof.get("no_ref_issued") is not True
            or proof.get("temporary_files_cleaned") is not True
            or proof.get("cleanup_directory_fsynced") is not True
            or not 0 < proof.get("partial_bytes_written", 0) < proof.get("expected_output_size", 0)):
        raise PartialArtifactProbeError("partial artifact proof differs from Runtime lineage")
    if kind == "postgresql":
        scoped = make_conninfo(
            profile["postgres_dsn"], options=f"-c search_path={row['pg_schema']}",
        )
        with psycopg.connect(scoped) as connection:
            work = connection.execute(
                "SELECT state,revision FROM work_items WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()
            attempt = connection.execute(
                "SELECT work_item_id,runtime_id,scope_id FROM attempts WHERE attempt_id=%s",
                (proof["attempt_id"],),
            ).fetchone()
            counts = tuple(connection.execute(query, (proof[key],)).fetchone()[0]
                           for query, key in (
                               ("SELECT count(*) FROM execution_receipts WHERE work_item_id=%s", "work_item_id"),
                               ("SELECT count(*) FROM evidence WHERE work_item_id=%s", "work_item_id"),
                               ("SELECT count(*) FROM accepted_state_revisions WHERE work_item_id=%s", "work_item_id"),
                               ("SELECT count(*) FROM command_dedup WHERE command_id=%s", "receipt_command_id"),
                               ("SELECT count(*) FROM domain_events WHERE command_id=%s", "receipt_command_id"),
                           ))
        if (work != ("candidate", 0)
                or attempt != (proof["work_item_id"], proof["runtime_id"], "local-scope")
                or any(counts)):
            raise PartialArtifactProbeError("PostgreSQL partial artifact acceptance boundary changed")
        return {"partial_domain_fenced": True, "partial_domain_zero_rows": True}
    if kind in {"sqlite", "driver", "os"}:
        cas_root = ledger.root / f"{SCENARIO}-cas"
        expected_path = cas_root / proof["expected_output_path"]
        if expected_path.exists() or list(cas_root.rglob(".artifact-*")):
            raise PartialArtifactProbeError("partial CAS file survived readback")
        control_ref = ArtifactRef.model_validate(proof["control_ref"], strict=True)
        try:
            with LocalArtifactStore(cas_root, "local-scope") as independent:
                control = independent.read(control_ref)
                if _sha(control) != proof["control_sha256"]:
                    raise PartialArtifactProbeError("complete artifact control changed")
                partial_ref = ArtifactRef(
                    path=proof["expected_output_path"],
                    sha256=proof["expected_output_sha256"],
                    size_bytes=proof["expected_output_size"],
                    media_type="application/octet-stream", kind="output",
                    scope_id="local-scope", immutable=True,
                )
                try:
                    independent.verify(partial_ref)
                except ArtifactError:
                    pass
                else:
                    raise PartialArtifactProbeError("partial output became an admissible ArtifactRef")
        except ArtifactError as exc:
            raise PartialArtifactProbeError("complete control artifact failed readback") from exc
        return {"complete_control_readback": True, "partial_output_absent": True,
                "temporary_files_absent": True}
    return {"partial_proof_readback": True}
