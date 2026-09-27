"""Same-run P1 acceptance probe over the real Domain and file Effect Gateway.

The delivered message uses the P1 fixture Driver; the receipt/evidence, Review,
ready snapshot, protected publication, and accepted revision below are real
Runtime operations in the scenario's isolated PostgreSQL schema. This does not
accept the ACS product candidate or replace an independent Gate Reviewer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from runtime.artifacts import LocalArtifactStore
from runtime.domain import DomainAuthority
from runtime.effects import LocalFileEffectGateway
from runtime.errors import AcceptanceGuardFailed
from runtime.models import (
    EffectReadback,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    LeaseRequest,
    TransitionRequest,
    WorkItemState,
)

SCENARIO = "P1-INTEGRATED-ACCEPTANCE"


class IntegratedAcceptanceRejected(RuntimeError):
    pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _context(authority: DomainAuthority, role: str, suffix: str, store: LocalArtifactStore):
    return DomainAuthority(authority._dsn, context=replace(
        authority.context,
        principal_ref=f"p1-integrated-{role}:{suffix}",
        grant_ref=f"grant:p1-integrated-{role}:{suffix}",
    ), artifact_store=store)


def run(
    authority: DomainAuthority, node: Any, ledger: Any, work_id: str,
    message_id: str, delivery_operation_id: str, commit: str, tree: str,
    suffix: str, issued_at: datetime, *,
    register_execution: Callable[..., Any], domain_command: Callable[..., Any],
    private_json: Callable[..., Any],
) -> dict[str, Any]:
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if (proof.get("message_id") != message_id
                or proof.get("delivery_operation_id") != delivery_operation_id
                or proof.get("source_commit") != commit or proof.get("source_tree") != tree):
            raise IntegratedAcceptanceRejected("integrated proof belongs to another delivery")
        return proof
    with authority._connect() as connection:
        attempts = connection.execute(
            "SELECT attempt_id,status FROM delivery_attempts WHERE message_id=%s ORDER BY ordinal",
            (message_id,),
        ).fetchall()
        response = connection.execute(
            "SELECT receipt_id,evidence_json FROM delivery_receipts "
            "WHERE message_id=%s AND layer='response_received'", (message_id,),
        ).fetchone()
    if len(attempts) != 1 or attempts[0][1] != "delivered" or response is None:
        raise IntegratedAcceptanceRejected("integrated candidate lacks delivered response")
    attempt_id = attempts[0][0]
    payload = _canonical({
        "message_id": message_id, "delivery_operation_id": delivery_operation_id,
        "response_receipt_id": response[0], "response": response[1],
        "source_commit": commit, "source_tree": tree,
    })
    cas_root = ledger.root / f"{SCENARIO}-cas"
    publication_root = ledger.root / f"{SCENARIO}-publication"
    resource_id = "integrated-publication-" + suffix
    operation_id = "integrated-publication-op-" + suffix
    effect_id = "integrated-effect-" + suffix
    evidence_id = "integrated-evidence-" + suffix
    review_id = "integrated-review-" + suffix
    with LocalArtifactStore(cas_root) as store:
        producer = DomainAuthority(authority._dsn, context=authority.context, artifact_store=store)
        producer.bootstrap_local_grant((
            "work_item.create", "delivery.manage", "message.send", "message.read",
            "runtime.invoke", "evidence.record", "work_item.read", "lease.acquire",
            "lease.release", "lease.inspect", "effect.write", "effect.read",
            "effect.register",
        ))
        owner, observer, signed = register_execution(
            producer, node, work_id, commit, tree, suffix, issued_at,
            execution_attempt_id=attempt_id, artifact_store=store,
        )
        binding = owner["execution_binding"]
        if (binding["attempt_id"] != attempt_id
                or binding["work_item_id"] != work_id
                or binding["source_baseline"] != commit
                or binding["source_commit"] != commit
                or binding["source_tree"] != tree):
            raise IntegratedAcceptanceRejected("signed execution differs from delivered Attempt")
        output_ref = store.put_bytes(payload, kind="output")
        readback_ref = store.put_bytes(_canonical({
            "message_id": message_id, "source_commit": commit,
            "output_sha256": output_ref.sha256,
        }), kind="readback")
        observed_at = datetime.now(UTC)
        receipt = ExecutionReceipt(
            receipt_id="integrated-execution-receipt-" + suffix,
            work_item_id=work_id, attempt_id=attempt_id,
            runtime_id=owner["runtime_id"], provider=binding["provider"],
            command_id=binding["execution_command_id"],
            operation_id=binding["execution_operation_id"],
            event_id=binding["execution_event_id"],
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            source_commit=commit, source_tree=tree,
            test_commands=("P1 delivered response and source-bound CAS readback",),
            test_exit_codes=(0,), test_exit_code=0,
            os="linux", toolchain="P1 local fixture Driver; real Domain and file Gateway",
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
            source_sync="same-run committed source snapshot",
            status="succeeded", observed_at=observed_at,
        )
        receipt_command = domain_command(
            observer, "execution.record", "work_item", work_id,
            suffix + ":integrated-execution", issued_at,
        )
        observer.record_execution_receipt(
            receipt_command, receipt,
            node_proof=signed(receipt_command, receipt, "receipt"),
        )
        bundle = EvidenceBundle(
            evidence_id=evidence_id, work_item_id=work_id,
            source_baseline=commit, candidate_ref=binding["candidate_ref"],
            producer_ref=producer.context.principal_ref,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", evidence_state="complete",
            execution_receipt=receipt, artifact_refs=(output_ref,),
            readback_refs=(readback_ref,), command_id=receipt.command_id,
            operation_id=receipt.operation_id, event_id=receipt.event_id,
            observed_at=observed_at,
        )
        evidence = EvidenceRecord(
            evidence_id=evidence_id, work_item_id=work_id,
            observer_ref=observer.context.principal_ref,
            source_class="directly_verified", baseline_ref=commit,
            artifact_sha256=output_ref.sha256,
            summary="Signed delivered-response output and independent CAS readback",
            bundle_ref=evidence_id, candidate_ref=binding["candidate_ref"],
            execution_receipt_ref=receipt.receipt_id,
            evidence_state="complete", producer_ref=producer.context.principal_ref,
            attempt_id=attempt_id, test_exit_code=0,
            artifact_refs=(output_ref,), readback_refs=(readback_ref,),
        )
        evidence_command = domain_command(
            producer, "evidence.record", "work_item", work_id,
            suffix + ":integrated-evidence", issued_at,
        )
        producer.record_evidence(evidence_command, evidence, bundle)
        reviewer = _context(authority, "reviewer", suffix, store)
        finalizer = _context(authority, "finalizer", suffix, store)
        reviewer.bootstrap_local_grant(("review.record", "work_item.read"))
        finalizer.bootstrap_local_grant((
            "review.assign", "work_item.transition", "acceptance.finalize",
            "work_item.read", "effect.read",
        ))
        assigned = finalizer.assign_reviewer(domain_command(
            finalizer, "review.assign", "work_item", work_id,
            suffix + ":integrated-assignment", issued_at,
        ), work_id, reviewer.context.principal_ref, reviewer.context.grant_ref)
        reviewed = reviewer.record_review(domain_command(
            reviewer, "review.record", "work_item", work_id,
            suffix + ":integrated-review", issued_at,
        ), review_id, work_id, "pass", evidence_id, commit)
        ready = finalizer.transition_work_item(domain_command(
            finalizer, "work_item.transition", "work_item", work_id,
            suffix + ":integrated-ready", issued_at,
        ), TransitionRequest(
            to_state=WorkItemState.ACCEPTANCE_READY,
            evidence_refs=(evidence_id,), review_ref=review_id,
        ))
        if ready.revision != 1 or ready.state != WorkItemState.ACCEPTANCE_READY:
            raise IntegratedAcceptanceRejected("reviewed candidate did not reach readiness")
        lease = producer.leases.acquire_lease(domain_command(
            producer, "lease.acquire", "lease", resource_id,
            suffix + ":integrated-lease", issued_at, revision=1,
        ), LeaseRequest(
            resource_id=resource_id, owner_attempt_id=attempt_id,
            owner_runtime_id=owner["runtime_id"], scope_id="local-scope",
            work_item_id=work_id, grant_ref=producer.context.grant_ref,
            authority_incarnation=producer.context.authority_incarnation,
            ttl_seconds=300,
        ))
        registration = {
            "effect_id": effect_id, "lease_id": lease["lease_id"],
            "resource_id": resource_id, "readback_ref": "output.txt",
            "operation_id": operation_id,
        }
        with (
            LocalFileEffectGateway(producer.leases, publication_root,
                                   scope_id="local-scope",
                                   resource_paths={resource_id: "output.txt"}) as writer,
            LocalFileEffectGateway(finalizer.leases, publication_root,
                                   scope_id="local-scope",
                                   resource_paths={resource_id: "output.txt"}) as reader,
        ):
            producer._effect_registration_gateway = writer
            before_command = domain_command(
                producer, "effect.register", "work_item", work_id,
                suffix + ":integrated-before-publication", issued_at, revision=1,
            )
            try:
                producer.register_effect(before_command, **registration)
            except AcceptanceGuardFailed as error:
                before_reason = str(error)
            else:
                raise IntegratedAcceptanceRejected("unpublished effect was registered")
            with producer._connect() as connection:
                denied_counts = {
                    table: connection.execute(
                        f"SELECT count(*) FROM {table} WHERE command_id=%s",
                        (before_command.command_id,),
                    ).fetchone()[0]
                    for table in ("command_dedup", "domain_events", "operations")
                }
                effect_before = connection.execute(
                    "SELECT count(*) FROM effects WHERE effect_id=%s", (effect_id,),
                ).fetchone()[0]
            if ("Gateway readback failed" not in before_reason
                    or any(denied_counts.values()) or effect_before != 0):
                raise IntegratedAcceptanceRejected("unpublished effect rejection was not atomic")
            owner_args = {
                "lease_id": lease["lease_id"], "resource_id": resource_id,
                "generation": lease["generation"],
                "fencing_token": lease["fencing_token"],
                "caller": producer.context, "attempt_id": attempt_id,
                "runtime_id": owner["runtime_id"], "scope_id": "local-scope",
                "grant_ref": producer.context.grant_ref,
                "authority_incarnation": producer.context.authority_incarnation,
            }
            written = writer.write(
                **owner_args, relative_path="output.txt", payload=payload,
                operation_id=operation_id,
            )
            if (written["sha256"] != output_ref.sha256
                    or written["bytes"] != output_ref.size_bytes):
                raise IntegratedAcceptanceRejected("protected publication differs from ready output")
            register_command = domain_command(
                producer, "effect.register", "work_item", work_id,
                suffix + ":integrated-register", issued_at, revision=1,
            )
            registered = producer.register_effect(register_command, **registration)
            released = producer.leases.release_lease(
                command=domain_command(
                    producer, "lease.release", "lease", resource_id,
                    suffix + ":integrated-release", issued_at, revision=1,
                ), lease_id=lease["lease_id"], resource_id=resource_id,
                generation=lease["generation"],
                fencing_token=lease["fencing_token"],
            )
            if released["status"] != "released":
                raise IntegratedAcceptanceRejected("publication Lease did not release")
            historical = reader.historical_readback(
                lease_id=lease["lease_id"], resource_id=resource_id,
                generation=lease["generation"],
                fencing_token=lease["fencing_token"],
                readback_ref="output.txt", caller=finalizer.context,
                scope_id="local-scope", grant_ref=finalizer.context.grant_ref,
                authority_incarnation=finalizer.context.authority_incarnation,
                expected_operation_id=operation_id,
            )
            if (historical["completion_state"] != "completed"
                    or historical["sha256"] != output_ref.sha256):
                raise IntegratedAcceptanceRejected("historical publication readback differs")

            def verify_effect(cursor, context, effect):
                observed = reader.historical_readback_in_transaction(
                    cursor, lease_id=effect["lease_id"],
                    resource_id=effect["resource_id"],
                    generation=effect["generation"],
                    fencing_token=effect["fencing_token"],
                    readback_ref=effect["readback_ref"], caller=context,
                    scope_id=effect["scope_id"], grant_ref=context.grant_ref,
                    authority_incarnation=context.authority_incarnation,
                    expected_operation_id=effect["operation_id"],
                )
                proof = {key: observed[key] for key in EffectReadback.model_fields
                         if key not in ("effect_id", "work_item_id")}
                proof.update(effect_id=effect["effect_id"],
                             work_item_id=effect["work_item_id"])
                return proof

            finalizer._effect_readback_verifier = verify_effect
            accepted = finalizer.transition_work_item(domain_command(
                finalizer, "work_item.transition", "work_item", work_id,
                suffix + ":integrated-accept", issued_at, revision=1,
            ), TransitionRequest(
                to_state=WorkItemState.ACCEPTED,
                evidence_refs=(evidence_id,), review_ref=review_id,
                effect_refs=(effect_id,), readback_refs=("output.txt",),
            ))
            if accepted.revision != 2 or accepted.state != WorkItemState.ACCEPTED:
                raise IntegratedAcceptanceRejected("published candidate was not accepted")
        store.verify(output_ref)
        store.verify(readback_ref)
        file_sha256 = _digest((publication_root / "output.txt").read_bytes())
        if file_sha256 != output_ref.sha256:
            raise IntegratedAcceptanceRejected("published file bytes differ from accepted output")
        with producer._connect() as connection:
            work = connection.execute(
                "SELECT state,revision,source_baseline FROM work_items WHERE work_item_id=%s",
                (work_id,),
            ).fetchone()
            snapshots = connection.execute(
                "SELECT revision,readiness_snapshot,baseline_ref,candidate_ref,evidence_refs,"
                "review_ref,effect_refs,readback_refs,readback_digest "
                "FROM accepted_state_revisions WHERE work_item_id=%s ORDER BY revision",
                (work_id,),
            ).fetchall()
            review = connection.execute(
                "SELECT reviewer_ref,verdict,evidence_ref,baseline_ref FROM reviews WHERE review_id=%s",
                (review_id,),
            ).fetchone()
            assignment = connection.execute(
                "SELECT reviewer_ref,reviewer_grant_ref,status,assigned_by,scope_id,"
                "assignment_revision,command_id,operation_id FROM reviewer_assignments "
                "WHERE work_item_id=%s AND reviewer_ref=%s",
                (work_id, reviewer.context.principal_ref),
            ).fetchone()
            effect = connection.execute(
                "SELECT status,operation_id,expected_sha256,expected_size_bytes,"
                "completion_state,completion_sha256,registration_command_id "
                "FROM effects WHERE effect_id=%s", (effect_id,),
            ).fetchone()
            counts = {
                table: connection.execute(
                    f"SELECT count(*) FROM {table} WHERE work_item_id=%s", (work_id,),
                ).fetchone()[0]
                for table in ("execution_receipts", "evidence", "evidence_bundles", "reviews")
            }
        if (work != ("accepted", 2, commit) or len(snapshots) != 2
                or snapshots[0][:4] != (1, True, commit, binding["candidate_ref"])
                or snapshots[1][:4] != (2, False, commit, binding["candidate_ref"])
                or snapshots[0][4:8] != ([evidence_id], review_id, [], [])
                or snapshots[1][4:8] != ([evidence_id], review_id, [effect_id], ["output.txt"])
                or not snapshots[0][8] or not snapshots[1][8]
                or review != (reviewer.context.principal_ref, "pass", evidence_id, commit)
                or assignment is None or assignment[0:5] != (
                    reviewer.context.principal_ref, reviewer.context.grant_ref,
                    "active", finalizer.context.principal_ref, "local-scope",
                ) or assignment[7] != assigned.operation_id
                or effect != ("verified", operation_id, output_ref.sha256,
                              output_ref.size_bytes, "completed",
                              historical["completion_sha256"], register_command.command_id)
                or any(count != 1 for count in counts.values())):
            raise IntegratedAcceptanceRejected("accepted revision or reviewed publication readback differs")
        proof = {
            "source_commit": commit, "source_tree": tree,
            "machine_id": node.machine_id, "node_id": node.node_id,
            "work_item_id": work_id, "message_id": message_id,
            "delivery_operation_id": delivery_operation_id,
            "delivery_attempt_id": attempt_id,
            "response_receipt_id": response[0],
            "execution_receipt_id": receipt.receipt_id,
            "execution_operation_id": receipt.operation_id,
            "candidate_ref": binding["candidate_ref"],
            "evidence_id": evidence_id, "review_id": review_id,
            "assigned_operation_id": assigned.operation_id,
            "review_operation_id": reviewed.operation_id,
            "ready_operation_id": ready.operation_id,
            "accepted_operation_id": accepted.operation_id,
            "ready_revision": 1, "accepted_revision": 2,
            "effect_id": effect_id,
            "effect_registration_operation_id": registered.operation_id,
            "effect_registration_command_id": register_command.command_id,
            "publication_operation_id": operation_id,
            "resource_id": resource_id, "lease_id": lease["lease_id"],
            "generation": lease["generation"],
            "output_sha256": output_ref.sha256,
            "output_size_bytes": output_ref.size_bytes,
            "readback_sha256": readback_ref.sha256,
            "file_sha256": file_sha256,
            "completion_sha256": historical["completion_sha256"],
            "before_publication_rejected": True,
            "before_publication_reason": before_reason,
            "before_publication_command_counts": denied_counts,
            "work": list(work),
            "snapshots": [list(item) for item in snapshots],
            "review": list(review), "assignment": list(assignment),
            "effect": list(effect),
            "counts": counts,
            "publication_relative_path": "output.txt",
            "cas_relative_path": output_ref.path,
            "finalizer_ref": finalizer.context.principal_ref,
            "finalizer_grant_ref": finalizer.context.grant_ref,
            "fixture_driver_scope": "same-run local FixtureDriver delivery; native model scenes separately bound",
        }
        private_json(proof_path, proof)
        return proof


def read_layer(profile: dict[str, Any], kind: str, ledger: Any,
               row: dict[str, Any], lineage: dict[str, Any]) -> dict[str, Any]:
    proof = lineage.get("integrated_acceptance_proof")
    proof_path = ledger.root / f"{SCENARIO}-proof.json"
    if (not isinstance(proof, dict) or not proof_path.is_file()
            or json.loads(proof_path.read_text(encoding="utf-8")) != proof
            or proof.get("message_id") != lineage["message_id"]
            or proof.get("delivery_operation_id") != lineage["operation_id"]
            or proof.get("delivery_attempt_id") != lineage["attempt_id"]
            or proof.get("source_commit") != row["source_commit"]
            or proof.get("source_tree") != row["source_tree"]
            or proof.get("machine_id") != profile["machine_id"]
            or proof.get("node_id") != profile["node_id"]
            or proof.get("ready_revision") != 1
            or proof.get("accepted_revision") != 2
            or proof.get("before_publication_rejected") is not True
            or any(proof.get("before_publication_command_counts", {}).values())):
        raise IntegratedAcceptanceRejected("integrated acceptance proof identity is incomplete")
    result = {"integrated_acceptance_proof_sha256": _digest(proof_path.read_bytes())}
    if kind == "postgresql":
        scoped = make_conninfo(profile["postgres_dsn"],
                               options=f"-c search_path={row['pg_schema']}")
        with psycopg.connect(scoped) as connection:
            work = connection.execute(
                "SELECT state,revision,source_baseline FROM work_items WHERE work_item_id=%s",
                (proof["work_item_id"],),
            ).fetchone()
            snapshots = connection.execute(
                "SELECT revision,readiness_snapshot,baseline_ref,candidate_ref,evidence_refs,"
                "review_ref,effect_refs,readback_refs,readback_digest "
                "FROM accepted_state_revisions WHERE work_item_id=%s ORDER BY revision",
                (proof["work_item_id"],),
            ).fetchall()
            review = connection.execute(
                "SELECT reviewer_ref,verdict,evidence_ref,baseline_ref FROM reviews WHERE review_id=%s",
                (proof["review_id"],),
            ).fetchone()
            assignment = connection.execute(
                "SELECT reviewer_ref,reviewer_grant_ref,status,assigned_by,scope_id,"
                "assignment_revision,command_id,operation_id FROM reviewer_assignments "
                "WHERE work_item_id=%s AND reviewer_ref=%s",
                (proof["work_item_id"], proof["review"][0]),
            ).fetchone()
            effect = connection.execute(
                "SELECT status,operation_id,expected_sha256,expected_size_bytes,"
                "completion_state,completion_sha256,registration_command_id "
                "FROM effects WHERE effect_id=%s", (proof["effect_id"],),
            ).fetchone()
            counts = {
                table: connection.execute(
                    f"SELECT count(*) FROM {table} WHERE work_item_id=%s",
                    (proof["work_item_id"],),
                ).fetchone()[0]
                for table in ("execution_receipts", "evidence", "evidence_bundles", "reviews")
            }
        if (work is None or review is None or assignment is None or effect is None
                or list(work) != proof["work"]
                or [list(item) for item in snapshots] != proof["snapshots"]
                or list(review) != proof["review"]
                or list(assignment) != proof["assignment"]
                or list(effect) != proof["effect"] or counts != proof["counts"]):
            raise IntegratedAcceptanceRejected("integrated PostgreSQL readback changed")
        result["integrated_postgresql_readback"] = True
    if kind in ("driver", "os"):
        publication = ledger.root / f"{SCENARIO}-publication" / proof["publication_relative_path"]
        cas = ledger.root / f"{SCENARIO}-cas" / proof["cas_relative_path"]
        if (not publication.is_file() or not cas.is_file()
                or _digest(publication.read_bytes()) != proof["output_sha256"]
                or _digest(cas.read_bytes()) != proof["output_sha256"]
                or publication.read_bytes() != cas.read_bytes()):
            raise IntegratedAcceptanceRejected("integrated publication or CAS bytes changed")
        result["integrated_published_file_sha256"] = proof["output_sha256"]
    if kind == "driver":
        scoped = make_conninfo(profile["postgres_dsn"],
                               options=f"-c search_path={row['pg_schema']}")
        base = DomainAuthority(scoped)
        finalizer = DomainAuthority(scoped, context=replace(
            base.context, principal_ref=proof["finalizer_ref"],
            grant_ref=proof["finalizer_grant_ref"],
        ))
        with finalizer._connect() as connection:
            lease = connection.execute(
                "SELECT generation,fencing_token FROM leases WHERE lease_id=%s",
                (proof["lease_id"],),
            ).fetchone()
        if lease is None or lease[0] != proof["generation"]:
            raise IntegratedAcceptanceRejected("integrated publication Lease changed")
        with LocalFileEffectGateway(
            finalizer.leases, ledger.root / f"{SCENARIO}-publication",
            scope_id="local-scope",
            resource_paths={proof["resource_id"]: proof["publication_relative_path"]},
        ) as reader:
            observed = reader.historical_readback(
                lease_id=proof["lease_id"], resource_id=proof["resource_id"],
                generation=lease[0], fencing_token=lease[1],
                readback_ref=proof["publication_relative_path"],
                caller=finalizer.context, scope_id="local-scope",
                grant_ref=finalizer.context.grant_ref,
                authority_incarnation=finalizer.context.authority_incarnation,
                expected_operation_id=proof["publication_operation_id"],
            )
        if (observed["completion_state"] != "completed"
                or observed["sha256"] != proof["output_sha256"]
                or observed["completion_sha256"] != proof["completion_sha256"]):
            raise IntegratedAcceptanceRejected("integrated historical Gateway readback changed")
        result["integrated_historical_gateway_readback"] = True
    return result
