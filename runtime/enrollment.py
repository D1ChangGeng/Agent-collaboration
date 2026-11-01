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
from runtime.lifetimes import earliest
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
        if self.authority.access_mode == "owner":
            ctx = self.authority.context
            cursor.execute("SELECT g.principal_ref FROM grants g JOIN scopes s ON s.scope_id=%s "
                "AND s.tenant_id=g.tenant_id WHERE g.tenant_id=%s AND g.grant_ref=%s "
                "AND g.authority_id=%s AND g.authority_incarnation=%s "
                "AND g.revoked_at IS NULL AND s.status='active'",
                (scope_id, ctx.tenant_id, grant_ref, ctx.authority_id, ctx.authority_incarnation))
            row = cursor.fetchone()
            if row is None:
                raise AuthorizationDenied(ctx.principal_ref, grant_ref)
            return row[0], None
        ctx = self.authority.context
        cursor.execute(
            "SELECT g.principal_ref,g.expires_at,g.permissions FROM grants g "
            "JOIN authority_instances a ON a.authority_id=g.authority_id AND a.authority_incarnation=g.authority_incarnation "
            "JOIN scopes s ON s.scope_id=g.scope_id AND s.tenant_id=g.tenant_id "
            "WHERE g.tenant_id=%s AND g.grant_ref=%s AND g.scope_id=%s AND g.authority_id=%s "
            "AND g.authority_incarnation=%s AND a.status='active' AND s.status='active' "
            # Enrollment observation must coexist with the caller's authorization
            # read locks while a remote receiver checks its own current binding.
            "AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() FOR SHARE OF g,a,s",
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
            "AND b.status='active' AND k.status='active' AND (%s OR b.expires_at>clock_timestamp()) FOR UPDATE OF b,k",
            (node["tenant_id"], node_id, node["current_binding_revision"], self.authority.access_mode == "owner"),
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
        return node, row[0], row[1], (None if self.authority.access_mode == "owner"
                                       else min(grant_expiry, self._time(row[0]["expires_at"])))

    def _active_runtime(self, cursor, runtime_id):
        cursor.execute("SELECT to_jsonb(r) FROM enrolled_runtimes r WHERE tenant_id=%s AND runtime_id=%s AND status='active' "
                       "AND (%s OR expires_at>clock_timestamp()) FOR UPDATE",
                       (self.authority.tenant_id, runtime_id, self.authority.access_mode == "owner"))
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
        return runtime, node, binding, key, (None if self.authority.access_mode == "owner"
            else min(valid_until, producer_expiry, self._time(runtime["expires_at"])))

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
        allowed = {("enrolled_node_bindings", "node_id"), ("enrolled_runtimes", "runtime_id")}
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
                                                  ("runtime.register",))
            _, operator_expiry = self._grant(cursor, command.grant_ref, request.scope_id, ("enrollment.manage",))
            expires = None if self.authority.access_mode == "owner" else self._time(request.expires_at)
            if self.authority.access_mode != "owner" and not self._now(cursor) < expires <= observer_expiry:
                raise AcceptanceGuardFailed("Node enrollment expiry exceeds its observer Grant")
            cursor.execute("SELECT 1 FROM enrolled_nodes WHERE tenant_id=%s AND node_id=%s FOR UPDATE", (command.tenant_id, command.target_id))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("Node identity is already enrolled")
            cursor.execute(
                "INSERT INTO enrolled_nodes(tenant_id,node_id,scope_id,agent_slot_id,observer_ref,observer_grant_ref,authority_id,"
                "authority_incarnation,revision,current_binding_revision,status,enrolled_by) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,1,1,'active',%s WHERE (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (command.tenant_id, command.target_id, request.scope_id, request.agent_slot_id, observer,
                 request.observer_grant_ref, command.authority_id, command.authority_incarnation, command.principal_ref,
                 earliest(command.deadline, operator_expiry), earliest(command.deadline, operator_expiry)),
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
            expires = None if self.authority.access_mode == "owner" else self._time(request.expires_at)
            if self.authority.access_mode != "owner" and not self._now(cursor) < expires <= observer_expiry:
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
                "UPDATE enrolled_nodes SET revision=%s,current_binding_revision=%s WHERE tenant_id=%s AND node_id=%s AND (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (result.revision, result.revision, command.tenant_id, command.target_id, earliest(command.deadline, operator_expiry), earliest(command.deadline, operator_expiry)),
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
                           "WHERE tenant_id=%s AND node_id=%s AND status='active' AND (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                           (result.revision, command.tenant_id, command.target_id, earliest(command.deadline, expiry), earliest(command.deadline, expiry)))
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
            expires = earliest(valid_until, command.deadline, self._now(cursor) + timedelta(seconds=request.ttl_seconds))
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
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s WHERE (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (f"challenge-{result.operation_id}", command.tenant_id, node["node_id"], binding["binding_revision"],
                 request.purpose, request.purpose_command_id, request.purpose_hash, encoded, expires,
                 command.command_id, result.operation_id, expires, expires),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Node challenge authorization expired")
            self._event(cursor, command, result, digest, "node.challenge_issued")
            return self._challenge_reply(cursor, result)

    def _record_owner_command(self, cursor, command, node_input, node, binding, purpose):
        """Persist the authenticated installation command, independently of a challenge."""
        digest = self.signing_hash(command, node_input)
        cursor.execute(
            "INSERT INTO owner_node_commands(tenant_id,command_id,node_id,node_binding_revision,purpose,"
            "command_json,input_json,canonical_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(tenant_id,command_id) DO NOTHING",
            (command.tenant_id, command.command_id, node["node_id"], binding["binding_revision"], purpose,
             command.model_dump_json(), json.dumps(node_input), digest),
        )
        self._owner_command(cursor, command.command_id, node["node_id"], binding["binding_revision"], purpose,
                            expected_hash=digest)

    def _owner_command(self, cursor, command_id, node_id, binding_revision, purpose, *, expected_hash=None):
        cursor.execute(
            "SELECT command_json,input_json,canonical_hash,recorded_at FROM owner_node_commands "
            "WHERE tenant_id=%s AND command_id=%s AND node_id=%s AND node_binding_revision=%s AND purpose=%s",
            (self.authority.tenant_id, command_id, node_id, binding_revision, purpose),
        )
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("authenticated owner command record is missing")
        command = CommandEnvelope.model_validate(row[0])
        if (self.signing_hash(command, row[1]) != row[2]
                or expected_hash is not None and row[2] != expected_hash
                or command.tenant_id != self.authority.tenant_id
                or command.command_id != command_id or command.command_type != purpose):
            raise AcceptanceGuardFailed("authenticated owner command record differs")
        return command, row[1], row[3]

    def verify_node_command(self, cursor, command, node_input, proof, purpose, *, node_id):
        """Verify/consume one real signature in the caller's command transaction.

        Each challenge has one immutable proof audit. A command may authenticate
        with a fresh challenge later; business dedup is independent of proofs.
        Old Node/key/boot proofs still fail current authentication.
        """
        if proof is None and self.authority.access_mode == "owner":
            node, binding, _key, _valid_until = self._active_node(cursor, node_id)
            self.authority._authorize(command, cursor, scope_id=node["scope_id"])
            self._record_owner_command(cursor, command, node_input, node, binding, purpose)
            return node, binding, None
        if proof is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        proof = self._typed(NodeCommandProof, proof) if proof is not None else None
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
                or (self.authority.access_mode != "owner" and self._time(challenge["expires_at"]) <= self._now(cursor))
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
        return node, binding, None if self.authority.access_mode == "owner" else earliest(valid_until, command.deadline, self._time(challenge["expires_at"]))

    def register_runtime(self, command, request: RuntimeRegistration, proof: NodeCommandProof | None = None):
        self._expect(command, "runtime.register", "runtime")
        request = self._typed(RuntimeRegistration, request)
        proof = self._typed(NodeCommandProof, proof) if proof is not None else None
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
            expires = None if self.authority.access_mode == "owner" else self._time(request.expires_at)
            if self.authority.access_mode != "owner" and not self._now(cursor) < expires <= min(producer_expiry, self._time(binding["expires_at"])):
                raise AcceptanceGuardFailed("Runtime expiry exceeds its Node/producer binding")
            cursor.execute("SELECT 1 FROM enrolled_runtimes WHERE tenant_id=%s AND runtime_id=%s FOR UPDATE",
                           (command.tenant_id, command.target_id))
            if cursor.fetchone() is not None:
                raise AcceptanceGuardFailed("Runtime identity is already registered")
            cursor.execute(
                "INSERT INTO enrolled_runtimes(tenant_id,runtime_id,node_id,node_binding_revision,node_boot_incarnation,scope_id,agent_slot_id,"
                "producer_ref,producer_grant_ref,observer_ref,observer_grant_ref,authority_id,authority_incarnation,provider,status,expires_at,command_id,operation_id) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s WHERE (%s::timestamptz IS NULL OR clock_timestamp()<%s)",
                (command.tenant_id, command.target_id, node["node_id"], binding["binding_revision"], binding["boot_incarnation"],
                 node["scope_id"], node["agent_slot_id"], producer, request.producer_grant_ref, node["observer_ref"],
                 node["observer_grant_ref"], command.authority_id, command.authority_incarnation, request.provider,
                 expires, command.command_id, result.operation_id, earliest(valid_until, producer_expiry), earliest(valid_until, producer_expiry)),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("Runtime registration authorization expired")
            event = self._event(cursor, command, result, digest, "runtime.registered")
            cursor.execute("UPDATE enrolled_runtimes SET event_id=%s WHERE tenant_id=%s AND runtime_id=%s",
                           (event, command.tenant_id, command.target_id))
            return self._reply(cursor, result, "enrolled_runtimes", "runtime_id")
