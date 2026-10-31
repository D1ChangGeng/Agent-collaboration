"""Archived signed execution/Attempt registration for historical fixtures only."""
from __future__ import annotations

import json

from nacl.exceptions import BadSignatureError

from runtime.enrollment import EnrollmentAuthority as CommunicationEnrollment
from runtime.enrollment_models import (
    AttemptRegistration,
    EnrollmentReply,
    NodeCommandProof,
)
from runtime.errors import (
    AcceptanceGuardFailed,
    RevisionConflict,
)
from runtime.lifetimes import earliest
from runtime.models import CommandEnvelope


class EnrollmentAuthority(CommunicationEnrollment):
    def _reply(self, cursor, result, table, id_column, *, revision=None):
        cursor.execute("SELECT view_json FROM enrollment_command_views WHERE tenant_id=%s AND command_id=%s",
                       (self.authority.tenant_id, result.command_id))
        previous = cursor.fetchone()
        if previous is not None:
            return EnrollmentReply(result=result, binding=previous[0])
        allowed = {("enrolled_node_bindings", "node_id"), ("enrolled_runtimes", "runtime_id"), ("attempts", "attempt_id")}
        if (table, id_column) not in allowed:
            raise ValueError("unsupported enrollment view")
        condition = " AND binding_revision=%s" if revision is not None else ""
        args = (self.authority.tenant_id, result.target_id) + ((revision,) if revision is not None else ())
        cursor.execute(f"SELECT to_jsonb(t) FROM {table} t WHERE tenant_id=%s AND {id_column}=%s{condition}", args)
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("committed enrollment result is unavailable")
        cursor.execute("INSERT INTO enrollment_command_views(tenant_id,command_id,view_json) VALUES (%s,%s,%s)",
                       (self.authority.tenant_id, result.command_id, json.dumps(row[0])))
        return EnrollmentReply(result=result, binding=row[0])


    def register_attempt(self, command, request: AttemptRegistration, proof: NodeCommandProof | None = None):
        """Register a signed Node execution-start observation; never start it.

        Execution command/operation/event IDs are this real observation command's
        Domain lineage. They are returned to the Node and never supplied in body.
        """
        self._expect(command, "attempt.register", "attempt")
        request = self._typed(AttemptRegistration, request)
        proof = self._typed(NodeCommandProof, proof) if proof is not None else None
        node_input = {"request": request.model_dump(mode="json")}
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "attempt.register")
            runtime_identity = self._runtime_identity(cursor, request.runtime_id)
            _, _, proof_expiry = self.verify_node_command(
                cursor, command, node_input, proof, "attempt.register", node_id=runtime_identity["node_id"])
            work = self.authority._lock_work_item(cursor, command, request.work_item_id, permission="attempt.register")
            result = self._result(command, 1, "attempt_registered")
            duplicate, digest = self.authority._dedup(cursor, command, result, node_input)
            if duplicate is not None:
                return self._reply(cursor, duplicate, "attempts", "attempt_id")
            if command.expected_revision != 0:
                raise RevisionConflict(command.target_id, command.expected_revision, 0)
            runtime, node, binding, _, runtime_expiry = self._active_runtime(cursor, request.runtime_id)
            if request.expected_work_item_revision != work[2]:
                raise RevisionConflict(request.work_item_id, request.expected_work_item_revision, int(work[2]))
            self.authority._require_confirmed_project_handoff(cursor, request.work_item_id)
            if (work[0] != runtime["scope_id"] or work[5] != runtime["agent_slot_id"] or work[3] != request.source_baseline):
                raise AcceptanceGuardFailed("Attempt WorkItem/Scope/Slot/source binding differs")
            observed_start = self._time(request.observed_started_at)
            if not self._time(runtime["registered_at"]) <= observed_start <= self._now(cursor):
                raise AcceptanceGuardFailed("signed execution-start observation is outside its Runtime lifetime")
            cursor.execute("SELECT 1 FROM attempts WHERE attempt_id=%s FOR UPDATE", (command.target_id,))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("Attempt identity is already registered")
            event = self._event(cursor, command, result, digest, "attempt.registered", related_work_item_id=request.work_item_id)
            cursor.execute(
                "INSERT INTO attempts(attempt_id,tenant_id,work_item_id,agent_slot_id,status,producer_ref,runtime_id,scope_id,grant_ref,"
                "authority_id,authority_incarnation,observer_ref,observer_grant_ref,execution_command_id,execution_operation_id,execution_event_id,"
                "provider,source_baseline,source_commit,source_tree,candidate_ref,execution_started_at,enrollment_runtime_id,enrollment_node_id,"
                "enrollment_node_binding_revision,enrollment_boot_incarnation,enrollment_registered_at,enrollment_proof_ref,enrollment_revision) "
                "SELECT %s,%s,%s,%s,'running',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),%s,1 "
                "WHERE (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (command.target_id, command.tenant_id, request.work_item_id, runtime["agent_slot_id"], runtime["producer_ref"],
                 runtime["runtime_id"], runtime["scope_id"], runtime["producer_grant_ref"], command.authority_id, command.authority_incarnation,
                 node["observer_ref"], node["observer_grant_ref"], command.command_id, result.operation_id, event, runtime["provider"],
                 request.source_baseline, request.source_commit, request.source_tree, request.candidate_ref, observed_start,
                 runtime["runtime_id"], node["node_id"], binding["binding_revision"], binding["boot_incarnation"], proof.challenge_id if proof else None,
                 earliest(runtime_expiry, proof_expiry), earliest(runtime_expiry, proof_expiry)),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Attempt registration authorization expired")
            return self._reply(cursor, result, "attempts", "attempt_id")


    def current_attempt_binding(self, cursor, attempt_id):
        """Required at every new protected write; NULL legacy enrollment is denied."""
        cursor.execute("SELECT to_jsonb(a) FROM attempts a WHERE tenant_id=%s AND attempt_id=%s FOR UPDATE",
                       (self.authority.tenant_id, attempt_id))
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("Attempt enrollment is missing")
        attempt = row[0]
        required = ("enrollment_runtime_id", "enrollment_node_id", "enrollment_node_binding_revision",
                    "enrollment_boot_incarnation", "enrollment_registered_at")
        if self.authority.access_mode != "owner":
            required += ("enrollment_proof_ref",)
        if any(attempt.get(field) is None for field in required):
            raise AcceptanceGuardFailed("Attempt has no authenticated enrollment")
        runtime, node, binding, key, expires = self._active_runtime(cursor, attempt["enrollment_runtime_id"])
        if (attempt["runtime_id"] != runtime["runtime_id"] or attempt["enrollment_node_id"] != node["node_id"]
                or attempt["enrollment_node_binding_revision"] != binding["binding_revision"]
                or attempt["enrollment_boot_incarnation"] != binding["boot_incarnation"]
                or attempt["scope_id"] != runtime["scope_id"] or attempt["agent_slot_id"] != runtime["agent_slot_id"]
                or attempt["grant_ref"] != runtime["producer_grant_ref"] or attempt["producer_ref"] != runtime["producer_ref"]
                or attempt["observer_ref"] != runtime["observer_ref"] or attempt["observer_grant_ref"] != runtime["observer_grant_ref"]
                or attempt["provider"] != runtime["provider"]):
            raise AcceptanceGuardFailed("Attempt authenticated enrollment binding differs")
        cursor.execute("SELECT scope_id,agent_slot_id,source_baseline FROM work_items WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
                       (self.authority.tenant_id, attempt["work_item_id"]))
        work = cursor.fetchone()
        if work != (attempt["scope_id"], attempt["agent_slot_id"], attempt["source_baseline"]):
            raise AcceptanceGuardFailed("Attempt current WorkItem/source binding differs")
        self.authority._require_confirmed_project_handoff(cursor, attempt["work_item_id"])
        if self.authority.access_mode == "owner" and attempt["enrollment_proof_ref"] is None:
            command, payload, recorded = self._owner_command(
                cursor, attempt["execution_command_id"], node["node_id"], binding["binding_revision"], "attempt.register")
            observation = self._typed(AttemptRegistration, payload["request"])
            if (command.target_id != attempt_id or observation.runtime_id != runtime["runtime_id"]
                    or observation.work_item_id != attempt["work_item_id"]
                    or observation.source_baseline != attempt["source_baseline"]
                    or observation.source_commit != attempt["source_commit"]
                    or observation.source_tree != attempt["source_tree"]
                    or observation.candidate_ref != attempt["candidate_ref"]
                    or observation.observed_started_at != self._time(attempt["execution_started_at"])
                    or recorded > self._time(attempt["enrollment_registered_at"])):
                raise AcceptanceGuardFailed("Attempt authenticated owner observation differs")
            return {"attempt": attempt, "runtime": runtime, "node": node, "binding": binding, "valid_until": None}
        cursor.execute(
            "SELECT p.command_json,p.input_json,p.signature,p.verified_at,c.message_hex,c.expires_at,c.consumed_by "
            "FROM enrolled_node_command_proofs p JOIN enrolled_node_challenges c ON c.challenge_id=p.challenge_id "
            "WHERE p.challenge_id=%s AND p.tenant_id=%s AND p.node_id=%s AND p.node_binding_revision=%s AND p.purpose='attempt.register'",
            (attempt["enrollment_proof_ref"], self.authority.tenant_id, node["node_id"], binding["binding_revision"]),
        )
        attestation = cursor.fetchone()
        if attestation is None:
            raise AcceptanceGuardFailed("Attempt enrollment attestation is missing")
        try:
            signed_command = CommandEnvelope.model_validate(attestation[0])
            signed_input = self._typed(AttemptRegistration, attestation[1]["request"])
            message = json.loads(bytes.fromhex(attestation[4]))
            if (signed_command.target_kind != "attempt" or signed_command.target_id != attempt_id
                    or signed_command.tenant_id != self.authority.tenant_id
                    or signed_command.authority_id != node["authority_id"]
                    or signed_command.authority_incarnation != node["authority_incarnation"]
                    or signed_command.command_id != attempt["execution_command_id"]
                    or signed_command.principal_ref != node["observer_ref"] or signed_command.grant_ref != node["observer_grant_ref"]
                    or attestation[6] != signed_command.command_id
                    or signed_input.runtime_id != attempt["runtime_id"] or signed_input.work_item_id != attempt["work_item_id"]
                    or signed_input.source_baseline != attempt["source_baseline"] or signed_input.source_commit != attempt["source_commit"]
                    or signed_input.source_tree != attempt["source_tree"] or signed_input.candidate_ref != attempt["candidate_ref"]
                    or signed_input.observed_started_at != self._time(attempt["execution_started_at"])
                    or message["purpose_hash"] != self.signing_hash(signed_command, attestation[1])
                    or message["schema"] != "acs-node-challenge/1" or message["purpose"] != "attempt.register"
                    or message["purpose_command_id"] != signed_command.command_id
                    or message["tenant_id"] != signed_command.tenant_id
                    or message["authority_id"] != signed_command.authority_id
                    or message["authority_incarnation"] != signed_command.authority_incarnation
                    or message["scope_id"] != runtime["scope_id"] or message["grant_ref"] != signed_command.grant_ref
                    or message["node_id"] != node["node_id"] or message["binding_revision"] != binding["binding_revision"]
                    or message["boot_incarnation"] != binding["boot_incarnation"] or message["key_id"] != key["key_id"]
                    or attestation[3] > self._time(attempt["enrollment_registered_at"])
                    or (self.authority.access_mode != "owner" and not self._time(attempt["enrollment_registered_at"]) < min(attestation[5], signed_command.deadline))):
                raise ValueError("Attempt attestation differs")
            self.verify_signature(key["public_key"], attestation[2], attestation[4])
        except (BadSignatureError, ValueError, KeyError, TypeError):
            raise AcceptanceGuardFailed("Attempt enrollment attestation is invalid") from None
        return {"attempt": attempt, "runtime": runtime, "node": node, "binding": binding, "valid_until": expires}


    def authorize_execution_receipt(self, cursor, command, receipt, proof):
        """Current authentication only; mutable new-record checks follow dedup."""
        self._expect(command, "execution.record", "work_item")
        cursor.execute("SELECT enrollment_node_id FROM attempts WHERE tenant_id=%s AND attempt_id=%s FOR UPDATE",
                       (self.authority.tenant_id, receipt.attempt_id))
        attempt = cursor.fetchone()
        if attempt is None or attempt[0] is None:
            raise AcceptanceGuardFailed("Attempt has no authenticated enrollment")
        node, binding, expires = self.verify_node_command(
            cursor, command, {"receipt": receipt.model_dump(mode="json")}, proof, "execution.record",
            node_id=attempt[0])
        return {"node": node, "binding": binding, "valid_until": expires,
                "proof_ref": self._typed(NodeCommandProof, proof).challenge_id if proof else None}


    def validate_new_execution_receipt(self, cursor, command, receipt, authentication):
        enrolled = self.current_attempt_binding(cursor, receipt.attempt_id)
        if (receipt.work_item_id != command.target_id or receipt.work_item_id != enrolled["attempt"]["work_item_id"]
                or receipt.runtime_id != enrolled["runtime"]["runtime_id"]
                or authentication["node"]["node_id"] != enrolled["node"]["node_id"]
                or authentication["binding"]["binding_revision"] != enrolled["binding"]["binding_revision"]):
            raise AcceptanceGuardFailed("execution receipt enrollment target differs")
        enrolled["valid_until"] = earliest(enrolled["valid_until"], authentication["valid_until"])
        enrolled["proof_ref"] = authentication["proof_ref"]
        return enrolled


    def seal_execution_receipt(self, cursor, command, receipt, enrolled):
        """Only actual DB record time establishes eligibility of historical proof."""
        cursor.execute(
            "UPDATE execution_receipts SET enrollment_node_id=%s,enrollment_node_binding_revision=%s,enrollment_runtime_id=%s,"
            "enrollment_proof_ref=%s,enrollment_recorded_at=clock_timestamp(),registration_command_id=%s "
            "WHERE tenant_id=%s AND work_item_id=%s AND receipt_id=%s AND enrollment_recorded_at IS NULL "
            "AND (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
            (enrolled["node"]["node_id"], enrolled["binding"]["binding_revision"], enrolled["runtime"]["runtime_id"],
             enrolled["proof_ref"], command.command_id, command.tenant_id, command.target_id, receipt.receipt_id, enrolled["valid_until"], enrolled["valid_until"]),
        )
        if cursor.rowcount != 1:
            raise AcceptanceGuardFailed("execution enrollment authorization expired before receipt recording")


    def _owner_receipt_provenance(self, cursor, receipt):
        cursor.execute(
            "SELECT to_jsonb(x),to_jsonb(a),to_jsonb(r),to_jsonb(b),to_jsonb(k) "
            "FROM execution_receipts x JOIN attempts a ON a.tenant_id=x.tenant_id AND a.attempt_id=x.attempt_id "
            "JOIN enrolled_runtimes r ON r.tenant_id=x.tenant_id AND r.runtime_id=x.enrollment_runtime_id "
            "JOIN enrolled_node_bindings b ON b.tenant_id=x.tenant_id AND b.node_id=x.enrollment_node_id "
            "AND b.binding_revision=x.enrollment_node_binding_revision "
            "JOIN enrolled_node_keys k ON k.key_id=b.key_id "
            "WHERE x.tenant_id=%s AND x.work_item_id=%s AND x.receipt_id=%s",
            (self.authority.tenant_id, receipt.work_item_id, receipt.receipt_id),
        )
        row = cursor.fetchone()
        if row is None or row[0]["enrollment_proof_ref"] is not None:
            return False
        record, attempt, runtime, binding, key = row
        command, payload, recorded = self._owner_command(
            cursor, record["registration_command_id"], binding["node_id"], binding["binding_revision"], "execution.record")
        if (record["receipt_json"] != receipt.model_dump(mode="json")
                or payload != {"receipt": receipt.model_dump(mode="json")}
                or command.target_kind != "work_item" or command.target_id != receipt.work_item_id
                or command.authority_id != runtime["authority_id"]
                or command.authority_incarnation != runtime["authority_incarnation"]
                or runtime["runtime_id"] != receipt.runtime_id or runtime["provider"] != receipt.provider
                or runtime["node_id"] != binding["node_id"]
                or runtime["node_binding_revision"] != binding["binding_revision"]
                or runtime["node_boot_incarnation"] != binding["boot_incarnation"]
                or attempt["enrollment_runtime_id"] != runtime["runtime_id"]
                or attempt["enrollment_node_id"] != binding["node_id"]
                or attempt["enrollment_node_binding_revision"] != binding["binding_revision"]
                or recorded > self._time(record["enrollment_recorded_at"])):
            raise AcceptanceGuardFailed("recorded execution owner provenance differs")
        self.validate_public_key(key["public_key"])
        return True


    def verify_receipt_provenance(self, cursor, receipt):
        """Existing signed receipts survive planned retirement and future-only revoke.

        This method never creates a receipt and never substitutes a caller's
        observed_at for the timestamp recorded by PostgreSQL at insertion.
        Current Source/Scope/Grant/Review/CAS/Policy checks remain in Domain.
        """
        if self.authority.access_mode == "owner" and self._owner_receipt_provenance(cursor, receipt):
            return
        cursor.execute(
            "SELECT to_jsonb(x),to_jsonb(a),to_jsonb(r),to_jsonb(b),to_jsonb(k),to_jsonb(p),to_jsonb(c) "
            "FROM execution_receipts x JOIN attempts a ON a.tenant_id=x.tenant_id AND a.attempt_id=x.attempt_id "
            "JOIN enrolled_runtimes r ON r.tenant_id=x.tenant_id AND r.runtime_id=x.enrollment_runtime_id "
            "JOIN enrolled_node_bindings b ON b.tenant_id=x.tenant_id AND b.node_id=x.enrollment_node_id "
            "AND b.binding_revision=x.enrollment_node_binding_revision "
            "JOIN enrolled_node_keys k ON k.key_id=b.key_id "
            "JOIN enrolled_node_command_proofs p ON p.challenge_id=x.enrollment_proof_ref "
            "JOIN enrolled_node_challenges c ON c.challenge_id=p.challenge_id "
            "WHERE x.tenant_id=%s AND x.work_item_id=%s AND x.receipt_id=%s FOR UPDATE OF x,a,r,b,k,p,c",
            (self.authority.tenant_id, receipt.work_item_id, receipt.receipt_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("recorded execution has no authenticated enrollment provenance")
        record, attempt, runtime, binding, key, proof, challenge = row
        self.validate_public_key(key["public_key"])
        if (record["enrollment_recorded_at"] is None or record["receipt_json"] != receipt.model_dump(mode="json")
                or runtime["runtime_id"] != receipt.runtime_id or runtime["provider"] != receipt.provider
                or runtime["node_id"] != binding["node_id"] or runtime["node_binding_revision"] != binding["binding_revision"]
                or runtime["node_boot_incarnation"] != binding["boot_incarnation"]
                or attempt["enrollment_runtime_id"] != runtime["runtime_id"]
                or attempt["enrollment_node_id"] != binding["node_id"]
                or attempt["enrollment_node_binding_revision"] != binding["binding_revision"]
                or attempt["enrollment_boot_incarnation"] != binding["boot_incarnation"]
                or proof["node_id"] != binding["node_id"] or proof["node_binding_revision"] != binding["binding_revision"]
                or proof["tenant_id"] != self.authority.tenant_id or proof["purpose"] != "execution.record"
                or proof["command_id"] != record["registration_command_id"]
                or proof["input_json"] != {"receipt": receipt.model_dump(mode="json")}
                or challenge["consumed_by"] != proof["command_id"]):
            raise AcceptanceGuardFailed("recorded execution enrollment provenance differs")
        recorded_at = self._time(record["enrollment_recorded_at"])
        starts = [runtime["registered_at"], binding["valid_from"], key["created_at"], proof["verified_at"]]
        ends = [] if self.authority.access_mode == "owner" else [runtime["expires_at"], binding["expires_at"], challenge["expires_at"]]
        ends.extend(value for value in (runtime["retired_at"], binding["retired_at"], key["retired_at"]) if value is not None)
        signed_command = CommandEnvelope.model_validate(proof["command_json"])
        if self.authority.access_mode != "owner":
            ends.append(signed_command.deadline)
        if (any(self._time(value) > recorded_at for value in starts)
                or any(recorded_at >= self._time(value) for value in ends)
                or signed_command.target_kind != "work_item" or signed_command.target_id != receipt.work_item_id
                or signed_command.principal_ref != attempt["observer_ref"] or signed_command.grant_ref != attempt["observer_grant_ref"]
                or challenge["purpose_hash"] != self.signing_hash(signed_command, proof["input_json"])):
            raise AcceptanceGuardFailed("execution receipt was not recorded within its enrollment validity")
        try:
            message = json.loads(bytes.fromhex(challenge["message_hex"]))
            if (message["node_id"] != binding["node_id"] or message["binding_revision"] != binding["binding_revision"]
                    or message["boot_incarnation"] != binding["boot_incarnation"] or message["key_id"] != key["key_id"]
                    or message["purpose_hash"] != challenge["purpose_hash"]
                    or message["schema"] != "acs-node-challenge/1" or message["purpose"] != "execution.record"
                    or message["purpose_command_id"] != signed_command.command_id
                    or message["tenant_id"] != signed_command.tenant_id
                    or message["authority_id"] != signed_command.authority_id
                    or message["authority_incarnation"] != signed_command.authority_incarnation
                    or message["scope_id"] != runtime["scope_id"] or message["grant_ref"] != signed_command.grant_ref):
                raise ValueError("challenge binding changed")
            self.verify_signature(key["public_key"], proof["signature"], challenge["message_hex"])
        except (BadSignatureError, ValueError, KeyError, TypeError):
            raise AcceptanceGuardFailed("recorded execution signature is invalid") from None
