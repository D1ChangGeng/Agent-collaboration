from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from nacl.bindings import crypto_core_ed25519_is_valid_point
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from runtime.enrollment_models import (
    AttemptRegistration,
    EnrollmentReply,
    NodeChallengeReply,
    NodeChallengeRequest,
    NodeCommandProof,
    NodeEnrollment,
    NodeRevocation,
    NodeRotation,
    RuntimeRegistration,
)
from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    RevisionConflict,
)
from runtime.models import CommandEnvelope, CommandResult


class EnrollmentAuthority:
    """Deterministic enrollment and Ed25519 possession proofs, not a launcher.

    Private keys are generated and retained by the Node. Only public keys,
    public challenges and command-bound signatures enter the Domain database.
    A signature proves possession/attribution, not OS or Harness conformance.
    """

    def __init__(self, authority: Any) -> None:
        self.authority = authority

    @staticmethod
    def _typed(model, value):
        data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        return model.model_validate_json(json.dumps(data), strict=True)

    @staticmethod
    def _time(value):
        value = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AcceptanceGuardFailed("enrollment timestamp must include a timezone")
        return value

    @staticmethod
    def _now(cursor):
        cursor.execute("SELECT clock_timestamp()")
        return cursor.fetchone()[0]

    @staticmethod
    def validate_public_key(public_key: str) -> bytes:
        """Canonical, on-curve, main-subgroup, non-small-order validation.

        Use the reviewed libsodium primitive, not custom curve arithmetic or a
        blacklist. The pinned PyNaCl wheel is also tested with the upstream
        ad3004e mixed-order regression vector.
        """
        try:
            encoded = bytes.fromhex(public_key)
            if not crypto_core_ed25519_is_valid_point(encoded):
                raise ValueError("invalid Ed25519 point")
        except (ValueError, TypeError):
            raise AcceptanceGuardFailed("Node public key failed strict Ed25519 point validation") from None
        return encoded

    @staticmethod
    def verify_signature(public_key: str, signature: str, message_hex: str) -> None:
        key = EnrollmentAuthority.validate_public_key(public_key)
        VerifyKey(key).verify(bytes.fromhex(message_hex), bytes.fromhex(signature))

    @staticmethod
    def signing_hash(command: CommandEnvelope, node_input: dict[str, Any]) -> str:
        return command.canonical_hash({"node_input": node_input})

    @staticmethod
    def _expect(command, name, target):
        if command.command_type != name or command.target_kind != target:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

    def _grant(self, cursor, grant_ref, scope_id, permissions):
        ctx = self.authority.context
        cursor.execute(
            "SELECT g.principal_ref,g.expires_at,g.permissions FROM grants g "
            "JOIN authority_instances a ON a.authority_id=g.authority_id AND a.authority_incarnation=g.authority_incarnation "
            "JOIN scopes s ON s.scope_id=g.scope_id AND s.tenant_id=g.tenant_id "
            "WHERE g.tenant_id=%s AND g.grant_ref=%s AND g.scope_id=%s AND g.authority_id=%s "
            "AND g.authority_incarnation=%s AND a.status='active' AND s.status='active' "
            "AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() FOR UPDATE OF g,a,s",
            (ctx.tenant_id, grant_ref, scope_id, ctx.authority_id, ctx.authority_incarnation),
        )
        row = cursor.fetchone()
        if row is None or not set(permissions).issubset(set(row[2] or ())):
            raise AuthorizationDenied(ctx.principal_ref, grant_ref)
        return row[0], row[1]

    def _slot(self, cursor, scope_id, slot_id):
        cursor.execute("SELECT 1 FROM agent_slots WHERE tenant_id=%s AND scope_id=%s AND agent_slot_id=%s AND status='active' FOR UPDATE",
                       (self.authority.tenant_id, scope_id, slot_id))
        if cursor.fetchone() is None:
            raise AcceptanceGuardFailed("enrollment Scope/AgentSlot binding is unavailable")

    def _node(self, cursor, node_id, *, active=True):
        cursor.execute("SELECT to_jsonb(n) FROM enrolled_nodes n WHERE tenant_id=%s AND node_id=%s FOR UPDATE",
                       (self.authority.tenant_id, node_id))
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("enrolled Node is missing")
        node = row[0]
        if active and node["status"] != "active":
            raise AcceptanceGuardFailed("enrolled Node is revoked")
        ctx = self.authority.context
        if (node["authority_id"], node["authority_incarnation"]) != (ctx.authority_id, ctx.authority_incarnation):
            raise AcceptanceGuardFailed("Node authority incarnation is not current")
        return node

    def _active_node(self, cursor, node_id, binding_revision=None):
        node = self._node(cursor, node_id)
        if binding_revision is not None and node["current_binding_revision"] != binding_revision:
            raise AcceptanceGuardFailed("Node boot/key binding is not current")
        cursor.execute(
            "SELECT to_jsonb(b),to_jsonb(k) FROM enrolled_node_bindings b JOIN enrolled_node_keys k ON k.key_id=b.key_id "
            "WHERE b.tenant_id=%s AND b.node_id=%s AND b.binding_revision=%s "
            "AND b.status='active' AND k.status='active' AND b.expires_at>clock_timestamp() FOR UPDATE OF b,k",
            (node["tenant_id"], node_id, node["current_binding_revision"]),
        )
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("Node boot/key binding is expired or retired")
        key_bytes = self.validate_public_key(row[1]["public_key"])
        if hashlib.sha256(key_bytes).hexdigest() != row[1]["fingerprint"]:
            raise AcceptanceGuardFailed("Node public-key fingerprint differs")
        self._slot(cursor, node["scope_id"], node["agent_slot_id"])
        observer, grant_expiry = self._grant(cursor, node["observer_grant_ref"], node["scope_id"], ())
        if observer != node["observer_ref"]:
            raise AcceptanceGuardFailed("Node observer Grant identity changed")
        return node, row[0], row[1], min(grant_expiry, self._time(row[0]["expires_at"]))

    def _active_runtime(self, cursor, runtime_id):
        cursor.execute("SELECT to_jsonb(r) FROM enrolled_runtimes r WHERE tenant_id=%s AND runtime_id=%s AND status='active' AND expires_at>clock_timestamp() FOR UPDATE",
                       (self.authority.tenant_id, runtime_id))
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("Runtime enrollment is missing, expired or retired")
        runtime = row[0]
        node, binding, key, valid_until = self._active_node(cursor, runtime["node_id"], runtime["node_binding_revision"])
        if (runtime["node_boot_incarnation"] != binding["boot_incarnation"]
                or runtime["scope_id"] != node["scope_id"] or runtime["agent_slot_id"] != node["agent_slot_id"]
                or runtime["observer_ref"] != node["observer_ref"] or runtime["observer_grant_ref"] != node["observer_grant_ref"]):
            raise AcceptanceGuardFailed("Runtime Node/Scope/Slot identity differs")
        producer, producer_expiry = self._grant(cursor, runtime["producer_grant_ref"], runtime["scope_id"], ())
        if producer != runtime["producer_ref"]:
            raise AcceptanceGuardFailed("Runtime producer Grant identity changed")
        return runtime, node, binding, key, min(valid_until, producer_expiry, self._time(runtime["expires_at"]))

    def _runtime_identity(self, cursor, runtime_id):
        cursor.execute("SELECT to_jsonb(r) FROM enrolled_runtimes r WHERE tenant_id=%s AND runtime_id=%s FOR UPDATE",
                       (self.authority.tenant_id, runtime_id))
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("Runtime enrollment is missing")
        return row[0]

    def _event(self, cursor, command, result, digest, topic, *, related_work_item_id=None):
        cursor.execute(
            "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,related_work_item_id,from_state,to_state,"
            "initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs,command_hash_version,canonical_hash,created_at) "
            "VALUES (%s,NULL,%s,%s,%s,NULL,%s,%s,'external_command',%s,%s,'[]',%s,%s,clock_timestamp()) RETURNING event_id::text",
            (command.tenant_id, command.target_kind, command.target_id, related_work_item_id, result.state,
             command.principal_ref, command.command_id, result.revision, command.hash_version, digest),
        )
        event_id = cursor.fetchone()[0]
        self.authority._operation(cursor, command, result.operation_id)
        self.authority._outbox(cursor, command, result.operation_id, topic,
                              {"target_kind": command.target_kind, "target_id": command.target_id, "event_id": event_id})
        return event_id

    @staticmethod
    def _result(command, revision, state):
        return CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                             target_id=command.target_id, revision=revision, state=state)

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

    def _key(self, cursor, node_id, public_key):
        fingerprint = hashlib.sha256(self.validate_public_key(public_key)).hexdigest()
        cursor.execute("SELECT key_id,tenant_id,node_id,status FROM enrolled_node_keys WHERE fingerprint=%s FOR UPDATE", (fingerprint,))
        row = cursor.fetchone()
        if row is not None:
            if (row[1], row[2], row[3]) != (self.authority.tenant_id, node_id, "active"):
                raise AcceptanceGuardFailed("Node key is shared, revoked or retired")
            return row[0]
        key_id = f"node-key-{uuid.uuid4()}"
        cursor.execute("INSERT INTO enrolled_node_keys(key_id,tenant_id,node_id,public_key,fingerprint,status) VALUES (%s,%s,%s,%s,%s,'active')",
                       (key_id, self.authority.tenant_id, node_id, public_key, fingerprint))
        return key_id

    def enroll_node(self, command, request: NodeEnrollment):
        self._expect(command, "node.enroll", "node")
        request = self._typed(NodeEnrollment, request)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "enrollment.manage", request.scope_id)
            result = self._result(command, 1, "node_enrolled")
            duplicate, digest = self.authority._dedup(cursor, command, result, {"request": request.model_dump(mode="json")})
            if duplicate is not None:
                return self._reply(cursor, duplicate, "enrolled_node_bindings", "node_id", revision=duplicate.revision)
            if command.expected_revision != 0:
                raise RevisionConflict(command.target_id, command.expected_revision, 0)
            self._slot(cursor, request.scope_id, request.agent_slot_id)
            observer, observer_expiry = self._grant(cursor, request.observer_grant_ref, request.scope_id,
                                                  ("runtime.register", "attempt.register", "execution.record"))
            _, operator_expiry = self._grant(cursor, command.grant_ref, request.scope_id, ("enrollment.manage",))
            expires = self._time(request.expires_at)
            if not self._now(cursor) < expires <= observer_expiry:
                raise AcceptanceGuardFailed("Node enrollment expiry exceeds its observer Grant")
            cursor.execute("SELECT 1 FROM enrolled_nodes WHERE tenant_id=%s AND node_id=%s FOR UPDATE", (command.tenant_id, command.target_id))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("Node identity is already enrolled")
            cursor.execute(
                "INSERT INTO enrolled_nodes(tenant_id,node_id,scope_id,agent_slot_id,observer_ref,observer_grant_ref,authority_id,"
                "authority_incarnation,revision,current_binding_revision,status,enrolled_by) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,1,1,'active',%s WHERE clock_timestamp()<%s",
                (command.tenant_id, command.target_id, request.scope_id, request.agent_slot_id, observer,
                 request.observer_grant_ref, command.authority_id, command.authority_incarnation, command.principal_ref,
                 min(command.deadline, operator_expiry)),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("enrollment authorization expired during registration")
            key = self._key(cursor, command.target_id, request.public_key)
            cursor.execute(
                "INSERT INTO enrolled_node_bindings(tenant_id,node_id,binding_revision,key_id,machine_id,boot_incarnation,status,expires_at,command_id,operation_id) "
                "VALUES (%s,%s,1,%s,%s,%s,'active',%s,%s,%s)",
                (command.tenant_id, command.target_id, key, request.machine_id, request.boot_incarnation,
                 expires, command.command_id, result.operation_id),
            )
            event = self._event(cursor, command, result, digest, "node.enrolled")
            cursor.execute("UPDATE enrolled_node_bindings SET event_id=%s WHERE tenant_id=%s AND node_id=%s AND binding_revision=1",
                           (event, command.tenant_id, command.target_id))
            return self._reply(cursor, result, "enrolled_node_bindings", "node_id", revision=1)

    def rotate_node(self, command, request: NodeRotation):
        self._expect(command, "node.rotate", "node")
        request = self._typed(NodeRotation, request)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "enrollment.manage")
            node = self._node(cursor, command.target_id)
            self.authority._authorize(command, cursor, "enrollment.manage", node["scope_id"])
            result = self._result(command, command.expected_revision + 1, "node_rotated")
            duplicate, digest = self.authority._dedup(cursor, command, result, {"request": request.model_dump(mode="json")})
            if duplicate is not None:
                return self._reply(cursor, duplicate, "enrolled_node_bindings", "node_id", revision=duplicate.revision)
            if command.expected_revision != node["revision"]:
                raise RevisionConflict(command.target_id, command.expected_revision, node["revision"])
            _, observer_expiry = self._grant(cursor, node["observer_grant_ref"], node["scope_id"], ())
            _, operator_expiry = self._grant(cursor, command.grant_ref, node["scope_id"], ("enrollment.manage",))
            expires = self._time(request.expires_at)
            if not self._now(cursor) < expires <= observer_expiry:
                raise AcceptanceGuardFailed("Node enrollment expiry exceeds its observer Grant")
            cursor.execute("SELECT 1 FROM enrolled_node_bindings WHERE tenant_id=%s AND node_id=%s AND boot_incarnation=%s",
                           (command.tenant_id, command.target_id, request.boot_incarnation))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("retired Node boot cannot be reactivated")
            new_key = self._key(cursor, command.target_id, request.public_key)
            cursor.execute("UPDATE enrolled_node_bindings SET status='retired',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND status='active'",
                           (command.tenant_id, command.target_id))
            cursor.execute("UPDATE enrolled_node_keys SET status='retired',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND key_id<>%s AND status='active'",
                           (command.tenant_id, command.target_id, new_key))
            cursor.execute("UPDATE enrolled_runtimes SET status='retired',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND status='active'",
                           (command.tenant_id, command.target_id))
            cursor.execute(
                "UPDATE enrolled_nodes SET revision=%s,current_binding_revision=%s WHERE tenant_id=%s AND node_id=%s AND clock_timestamp()<%s",
                (result.revision, result.revision, command.tenant_id, command.target_id, min(command.deadline, operator_expiry)),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("enrollment authorization expired during rotation")
            cursor.execute(
                "INSERT INTO enrolled_node_bindings(tenant_id,node_id,binding_revision,key_id,machine_id,boot_incarnation,status,expires_at,command_id,operation_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)",
                (command.tenant_id, command.target_id, result.revision, new_key, request.machine_id,
                 request.boot_incarnation, expires, command.command_id, result.operation_id),
            )
            event = self._event(cursor, command, result, digest, "node.rotated")
            cursor.execute("UPDATE enrolled_node_bindings SET event_id=%s WHERE tenant_id=%s AND node_id=%s AND binding_revision=%s",
                           (event, command.tenant_id, command.target_id, result.revision))
            return self._reply(cursor, result, "enrolled_node_bindings", "node_id", revision=result.revision)

    def revoke_node(self, command, request: NodeRevocation):
        self._expect(command, "node.revoke", "node")
        request = self._typed(NodeRevocation, request)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "enrollment.manage")
            node = self._node(cursor, command.target_id, active=False)
            self.authority._authorize(command, cursor, "enrollment.manage", node["scope_id"])
            result = self._result(command, command.expected_revision + 1, "node_revoked")
            duplicate, digest = self.authority._dedup(cursor, command, result, {"request": request.model_dump(mode="json"), "policy": "block_future_only"})
            if duplicate is not None:
                return duplicate
            if command.expected_revision != node["revision"]:
                raise RevisionConflict(command.target_id, command.expected_revision, node["revision"])
            _, expiry = self._grant(cursor, command.grant_ref, node["scope_id"], ("enrollment.manage",))
            cursor.execute("UPDATE enrolled_nodes SET status='revoked',revision=%s,revoked_at=clock_timestamp(),revocation_policy='block_future_only' "
                           "WHERE tenant_id=%s AND node_id=%s AND status='active' AND clock_timestamp()<%s",
                           (result.revision, command.tenant_id, command.target_id, min(command.deadline, expiry)))
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Node is already revoked or revocation authorization expired")
            cursor.execute("UPDATE enrolled_node_bindings SET status='revoked',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND status='active'",
                           (command.tenant_id, command.target_id))
            cursor.execute("UPDATE enrolled_node_keys SET status='revoked',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND status='active'",
                           (command.tenant_id, command.target_id))
            cursor.execute("UPDATE enrolled_runtimes SET status='revoked',retired_at=clock_timestamp() WHERE tenant_id=%s AND node_id=%s AND status='active'",
                           (command.tenant_id, command.target_id))
            self._event(cursor, command, result, digest, "node.revoked")
            return result

    def _challenge_reply(self, cursor, result):
        cursor.execute("SELECT challenge_id,message_hex,expires_at FROM enrolled_node_challenges WHERE tenant_id=%s AND issuance_operation_id=%s",
                       (self.authority.tenant_id, result.operation_id))
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("committed Node challenge is missing")
        return NodeChallengeReply(result=result, challenge_id=row[0], message_hex=row[1], expires_at=row[2])

    def challenge_node(self, command, request: NodeChallengeRequest):
        self._expect(command, "node.challenge", "node")
        request = self._typed(NodeChallengeRequest, request)
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, request.purpose)
            node, binding, key, valid_until = self._active_node(cursor, command.target_id)
            self.authority._authorize(command, cursor, request.purpose, node["scope_id"])
            if (command.principal_ref, command.grant_ref) != (node["observer_ref"], node["observer_grant_ref"]):
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            result = self._result(command, node["revision"], "node_challenge")
            duplicate, digest = self.authority._dedup(cursor, command, result, {"request": request.model_dump(mode="json")})
            if duplicate is not None:
                return self._challenge_reply(cursor, duplicate)
            if command.expected_revision != node["revision"]:
                raise RevisionConflict(command.target_id, command.expected_revision, node["revision"])
            expires = min(valid_until, command.deadline, self._now(cursor) + timedelta(seconds=request.ttl_seconds))
            message = {
                "schema": "acs-node-challenge/1", "tenant_id": command.tenant_id,
                "authority_id": command.authority_id, "authority_incarnation": command.authority_incarnation,
                "node_id": node["node_id"], "binding_revision": binding["binding_revision"],
                "boot_incarnation": binding["boot_incarnation"], "key_id": key["key_id"],
                "scope_id": node["scope_id"], "grant_ref": node["observer_grant_ref"],
                "purpose": request.purpose, "purpose_command_id": request.purpose_command_id,
                "purpose_hash": request.purpose_hash, "nonce": secrets.token_hex(32),
            }
            encoded = json.dumps(message, sort_keys=True, separators=(",", ":")).encode().hex()
            cursor.execute(
                "INSERT INTO enrolled_node_challenges(challenge_id,tenant_id,node_id,node_binding_revision,purpose,purpose_command_id,"
                "purpose_hash,message_hex,expires_at,issuance_command_id,issuance_operation_id) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s WHERE clock_timestamp()<%s",
                (f"challenge-{result.operation_id}", command.tenant_id, node["node_id"], binding["binding_revision"],
                 request.purpose, request.purpose_command_id, request.purpose_hash, encoded, expires,
                 command.command_id, result.operation_id, expires),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Node challenge authorization expired")
            self._event(cursor, command, result, digest, "node.challenge_issued")
            return self._challenge_reply(cursor, result)

    def verify_node_command(self, cursor, command, node_input, proof, purpose, *, node_id):
        """Verify/consume one real signature in the caller's command transaction.

        Each challenge has one immutable proof audit. A command may authenticate
        with a fresh challenge later; business dedup is independent of proofs.
        Old Node/key/boot proofs still fail current authentication.
        """
        if proof is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        proof = self._typed(NodeCommandProof, proof)
        node, binding, key, valid_until = self._active_node(cursor, node_id)
        binding_revision = binding["binding_revision"]
        self.authority._authorize(command, cursor, purpose, node["scope_id"])
        if (command.principal_ref, command.grant_ref) != (node["observer_ref"], node["observer_grant_ref"]):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute("SELECT to_jsonb(c) FROM enrolled_node_challenges c WHERE challenge_id=%s AND tenant_id=%s FOR UPDATE",
                       (proof.challenge_id, command.tenant_id))
        row = cursor.fetchone()
        if row is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        challenge = row[0]
        expected_hash = self.signing_hash(command, node_input)
        if (challenge["node_id"] != node_id or challenge["node_binding_revision"] != binding_revision
                or challenge["purpose"] != purpose or challenge["purpose_command_id"] != command.command_id
                or challenge["purpose_hash"] != expected_hash
                or self._time(challenge["expires_at"]) <= self._now(cursor)
                or challenge["consumed_by"] not in (None, command.command_id)):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        try:
            message = json.loads(bytes.fromhex(challenge["message_hex"]))
            expected_message = {
                "schema": "acs-node-challenge/1", "tenant_id": command.tenant_id,
                "authority_id": command.authority_id, "authority_incarnation": command.authority_incarnation,
                "node_id": node_id, "binding_revision": binding_revision,
                "boot_incarnation": binding["boot_incarnation"], "key_id": key["key_id"],
                "scope_id": node["scope_id"], "grant_ref": command.grant_ref,
                "purpose": purpose, "purpose_command_id": command.command_id,
                "purpose_hash": expected_hash, "nonce": message.get("nonce"),
            }
            nonce = message.get("nonce")
            if (message != expected_message or not isinstance(nonce, str) or len(nonce) != 64
                    or any(char not in "0123456789abcdef" for char in nonce)):
                raise ValueError("signed challenge context differs")
            self.verify_signature(key["public_key"], proof.signature, challenge["message_hex"])
        except (BadSignatureError, ValueError, TypeError, AttributeError):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref) from None
        cursor.execute("SELECT challenge_id,signature,command_json,input_json FROM enrolled_node_command_proofs "
                       "WHERE tenant_id=%s AND challenge_id=%s FOR UPDATE",
                       (command.tenant_id, proof.challenge_id))
        existing = cursor.fetchall()
        if existing:
            if (len(existing) != 1 or existing[0][0] != proof.challenge_id or existing[0][1] != proof.signature
                    or existing[0][2] != command.model_dump(mode="json") or existing[0][3] != node_input):
                raise IdempotencyConflict(command.idempotency_key)
        else:
            cursor.execute(
                "INSERT INTO enrolled_node_command_proofs(challenge_id,tenant_id,node_id,node_binding_revision,command_id,purpose,signature,command_json,input_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (proof.challenge_id, command.tenant_id, node_id, binding_revision, command.command_id, purpose,
                 proof.signature, command.model_dump_json(), json.dumps(node_input)),
            )
            cursor.execute("UPDATE enrolled_node_challenges SET consumed_by=%s WHERE challenge_id=%s",
                           (command.command_id, proof.challenge_id))
        return node, binding, min(valid_until, command.deadline, self._time(challenge["expires_at"]))

    def register_runtime(self, command, request: RuntimeRegistration, proof: NodeCommandProof):
        self._expect(command, "runtime.register", "runtime")
        request = self._typed(RuntimeRegistration, request)
        proof = self._typed(NodeCommandProof, proof)
        node_input = {"request": request.model_dump(mode="json")}
        with self.authority._connect() as connection, connection.cursor() as cursor:
            self.authority._authorize(command, cursor, "runtime.register")
            node, binding, valid_until = self.verify_node_command(
                cursor, command, node_input, proof, "runtime.register", node_id=request.node_id)
            result = self._result(command, 1, "runtime_registered")
            duplicate, digest = self.authority._dedup(cursor, command, result, node_input)
            if duplicate is not None:
                return self._reply(cursor, duplicate, "enrolled_runtimes", "runtime_id")
            if command.expected_revision != 0:
                raise RevisionConflict(command.target_id, command.expected_revision, 0)
            if request.node_binding_revision != binding["binding_revision"]:
                raise AcceptanceGuardFailed("Node boot/key binding is not current")
            producer, producer_expiry = self._grant(cursor, request.producer_grant_ref, node["scope_id"], ())
            expires = self._time(request.expires_at)
            if not self._now(cursor) < expires <= min(producer_expiry, self._time(binding["expires_at"])):
                raise AcceptanceGuardFailed("Runtime expiry exceeds its Node/producer binding")
            cursor.execute("SELECT 1 FROM enrolled_runtimes WHERE tenant_id=%s AND runtime_id=%s FOR UPDATE",
                           (command.tenant_id, command.target_id))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("Runtime identity is already registered")
            cursor.execute(
                "INSERT INTO enrolled_runtimes(tenant_id,runtime_id,node_id,node_binding_revision,node_boot_incarnation,scope_id,agent_slot_id,"
                "producer_ref,producer_grant_ref,observer_ref,observer_grant_ref,authority_id,authority_incarnation,provider,status,expires_at,command_id,operation_id) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s WHERE clock_timestamp()<%s",
                (command.tenant_id, command.target_id, node["node_id"], binding["binding_revision"], binding["boot_incarnation"],
                 node["scope_id"], node["agent_slot_id"], producer, request.producer_grant_ref, node["observer_ref"],
                 node["observer_grant_ref"], command.authority_id, command.authority_incarnation, request.provider,
                 expires, command.command_id, result.operation_id, min(valid_until, producer_expiry)),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Runtime registration authorization expired")
            event = self._event(cursor, command, result, digest, "runtime.registered")
            cursor.execute("UPDATE enrolled_runtimes SET event_id=%s WHERE tenant_id=%s AND runtime_id=%s",
                           (event, command.tenant_id, command.target_id))
            return self._reply(cursor, result, "enrolled_runtimes", "runtime_id")

    def register_attempt(self, command, request: AttemptRegistration, proof: NodeCommandProof):
        """Register a signed Node execution-start observation; never start it.

        Execution command/operation/event IDs are this real observation command's
        Domain lineage. They are returned to the Node and never supplied in body.
        """
        self._expect(command, "attempt.register", "attempt")
        request = self._typed(AttemptRegistration, request)
        proof = self._typed(NodeCommandProof, proof)
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
                "WHERE clock_timestamp()<%s",
                (command.target_id, command.tenant_id, request.work_item_id, runtime["agent_slot_id"], runtime["producer_ref"],
                 runtime["runtime_id"], runtime["scope_id"], runtime["producer_grant_ref"], command.authority_id, command.authority_incarnation,
                 node["observer_ref"], node["observer_grant_ref"], command.command_id, result.operation_id, event, runtime["provider"],
                 request.source_baseline, request.source_commit, request.source_tree, request.candidate_ref, observed_start,
                 runtime["runtime_id"], node["node_id"], binding["binding_revision"], binding["boot_incarnation"], proof.challenge_id,
                 min(runtime_expiry, proof_expiry)),
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
                    "enrollment_boot_incarnation", "enrollment_registered_at", "enrollment_proof_ref")
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
                    or not attestation[3] <= self._time(attempt["enrollment_registered_at"]) < min(attestation[5], signed_command.deadline)):
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
                "proof_ref": self._typed(NodeCommandProof, proof).challenge_id}

    def validate_new_execution_receipt(self, cursor, command, receipt, authentication):
        enrolled = self.current_attempt_binding(cursor, receipt.attempt_id)
        if (receipt.work_item_id != command.target_id or receipt.work_item_id != enrolled["attempt"]["work_item_id"]
                or receipt.runtime_id != enrolled["runtime"]["runtime_id"]
                or authentication["node"]["node_id"] != enrolled["node"]["node_id"]
                or authentication["binding"]["binding_revision"] != enrolled["binding"]["binding_revision"]):
            raise AcceptanceGuardFailed("execution receipt enrollment target differs")
        enrolled["valid_until"] = min(enrolled["valid_until"], authentication["valid_until"])
        enrolled["proof_ref"] = authentication["proof_ref"]
        return enrolled

    def seal_execution_receipt(self, cursor, command, receipt, enrolled):
        """Only actual DB record time establishes eligibility of historical proof."""
        cursor.execute(
            "UPDATE execution_receipts SET enrollment_node_id=%s,enrollment_node_binding_revision=%s,enrollment_runtime_id=%s,"
            "enrollment_proof_ref=%s,enrollment_recorded_at=clock_timestamp(),registration_command_id=%s "
            "WHERE tenant_id=%s AND work_item_id=%s AND receipt_id=%s AND enrollment_recorded_at IS NULL "
            "AND clock_timestamp()<%s",
            (enrolled["node"]["node_id"], enrolled["binding"]["binding_revision"], enrolled["runtime"]["runtime_id"],
             enrolled["proof_ref"], command.command_id, command.tenant_id, command.target_id, receipt.receipt_id, enrolled["valid_until"]),
        )
        if cursor.rowcount != 1:
            raise AcceptanceGuardFailed("execution enrollment authorization expired before receipt recording")

    def verify_receipt_provenance(self, cursor, receipt):
        """Existing signed receipts survive planned retirement and future-only revoke.

        This method never creates a receipt and never substitutes a caller's
        observed_at for the timestamp recorded by PostgreSQL at insertion.
        Current Source/Scope/Grant/Review/CAS/Policy checks remain in Domain.
        """
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
        ends = [runtime["expires_at"], binding["expires_at"], challenge["expires_at"]]
        ends.extend(value for value in (runtime["retired_at"], binding["retired_at"], key["retired_at"]) if value is not None)
        signed_command = CommandEnvelope.model_validate(proof["command_json"])
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
