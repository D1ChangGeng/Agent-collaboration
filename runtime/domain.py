from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import psycopg

from runtime.errors import (
    AcceptanceGuardFailed,
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidTransition,
    NotFound,
    RevisionConflict,
    RuntimeErrorBase,
    SchemaAdoptionError,
)
from runtime.lease_authority import LeaseAuthority
from runtime.migrations import LegacyCommandRecord, classify_replay
from runtime.models import (
    ArtifactRef,
    AuthenticatedContext,
    CommandEnvelope,
    CommandResult,
    EffectReadback,
    EvidenceBundle,
    EvidenceRecord,
    ExecutionReceipt,
    TransitionRequest,
    WorkItemState,
)


class DomainAuthority:
    """PostgreSQL Domain authority for the local Runtime profile."""

    SCHEMA_NAME = "acs-p1-runtime"
    SCHEMA_VERSION = "1.8"

    _KNOWN_SCHEMA_MIGRATIONS: ClassVar[set[tuple[str, str]]] = {
        ("1.7", "a3eb11f7afdccfedab5e7f7c41c861f3b9d8f4853460cdd948b8fc77e23d8132"),
        ("1.6", "89400be6a5c44f419ef73fe6661f907c858c11a397407662270fe0a79e169c73"),
        ("1.5", "c5faeecc4a9a6b152eb288f8f5d6cf3a1b4492d464f10d931535d3f737421fee"),
        ("1.4", "8f12aa29f385194b436f930422d5dafebc432d15bdf1a4bafe94294d8f744deb"),
        ("1.3", "0e3600dc7ed3b7fac727670f5c8fec0b00c6e100063e63a3f149661631dccea4"),
        (
            "1.0",
            "415c76f2778e1b1b33aa2533f14140511cb7c00bd0ebbd47ff8fb3a007578a87",
        ),
        (
            "1.1",
            "ea0097e39fb023c5130cb924d0faf34429f2f6968056b00a72042af1d78cdd92",
        ),
        (
            "1.2",
            "95e952142fc3d55d4eda3211852dee823e48aad6d793890716dc2365d2cbdd84",
        ),
        (
            "1.2",
            "312465f388be994fd1a2b308bd7f1c6e7c8354be5dfd54792fcb2be20ef13339",
        ),
    }

    def __init__(
        self,
        dsn: str,
        context: AuthenticatedContext | None = None,
        artifact_store: Any | None = None,
        *,
        authority_binding: tuple[str, str] = ("acs-p1-authority", "local-1"),
        effect_readback_verifier: Any | None = None,
        effect_registration_gateway: Any | None = None,
        delivery_endpoints: Mapping[str, Any] | None = None,
    ) -> None:
        self._dsn = dsn
        self._authority_binding = authority_binding
        self.context = context or AuthenticatedContext(
            "local-tenant",
            "acs-p1-authority",
            "local-1",
            "agent:engineer",
            "grant:p1",
        )
        self._artifact_store = artifact_store
        self._effect_readback_verifier = effect_readback_verifier
        self._effect_registration_gateway = effect_registration_gateway
        self._delivery_endpoints = dict(delivery_endpoints or {})

    def send_message(self, command: CommandEnvelope, packet: Any, *, endpoint_id: str,
                     binding_revision: int) -> CommandResult:
        from runtime.delivery import DeliveryService

        return DeliveryService(self, self._delivery_endpoints).send_message(
            command, packet, endpoint_id=endpoint_id, binding_revision=binding_revision,
        )

    def bind_message_endpoint(self, command: CommandEnvelope, request: Any) -> CommandResult:
        from runtime.delivery import DeliveryService

        return DeliveryService(self, self._delivery_endpoints).bind_endpoint(command, request)

    def read_message(self, command: CommandEnvelope, message_id: str) -> dict[str, Any]:
        from runtime.delivery import DeliveryService

        return DeliveryService(self, self._delivery_endpoints).inspect(command, message_id)

    def register_effect(
        self, command: CommandEnvelope, *, effect_id: str, lease_id: str,
        resource_id: str, readback_ref: str, operation_id: str,
    ) -> CommandResult:
        from runtime.effect_domain import EffectDomain

        return EffectDomain(self, self._effect_registration_gateway).register_effect(
            command, effect_id=effect_id, lease_id=lease_id, resource_id=resource_id,
            readback_ref=readback_ref, operation_id=operation_id,
        )

    def reconcile_effect(self, command: CommandEnvelope, *, effect_id: str) -> CommandResult:
        from runtime.effect_domain import EffectDomain

        return EffectDomain(self, self._effect_registration_gateway).reconcile_effect(
            command, effect_id=effect_id,
        )

    @property
    def enrollment(self):
        from runtime.enrollment import EnrollmentAuthority
        return EnrollmentAuthority(self)

    @property
    def receiver_transport(self):
        from runtime.receiver_domain import ReceiverTransportAuthority

        return ReceiverTransportAuthority(self)

    def register_authority_transport_key(self, command, request):
        return self.receiver_transport.register_authority_key(command, request)

    def register_receiver_connection(self, command, request):
        return self.receiver_transport.register_connection(command, request)

    def register_receiver_endpoint(self, command, request):
        return self.receiver_transport.register_endpoint(command, request)

    def enroll_node(self, command, request):
        return self.enrollment.enroll_node(command, request)

    def rotate_node(self, command, request):
        return self.enrollment.rotate_node(command, request)

    def revoke_node(self, command, request):
        return self.enrollment.revoke_node(command, request)

    def challenge_node(self, command, request):
        return self.enrollment.challenge_node(command, request)

    def register_runtime(self, command, request, proof):
        return self.enrollment.register_runtime(command, request, proof)

    def register_attempt(self, command, request, proof):
        return self.enrollment.register_attempt(command, request, proof)

    @property
    def leases(self) -> LeaseAuthority:
        return LeaseAuthority(self)

    @property
    def tenant_id(self) -> str:
        return self.context.tenant_id

    @property
    def authority_id(self) -> str:
        return self.context.authority_id

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(schema.encode("utf-8"))
            cursor.execute(
                "SELECT schema_version,schema_checksum "
                "FROM runtime_schema_metadata "
                "WHERE schema_name=%s FOR UPDATE",
                (self.SCHEMA_NAME,),
            )
            metadata = cursor.fetchone()

            if metadata is None:
                cursor.execute(
                    "INSERT INTO runtime_schema_metadata"
                    "(schema_name,schema_version,schema_checksum) "
                    "VALUES (%s,%s,%s)",
                    (self.SCHEMA_NAME, self.SCHEMA_VERSION, checksum),
                )
            elif (
                str(metadata[0]) == self.SCHEMA_VERSION
                and str(metadata[1]) == checksum
            ):
                pass
            elif (str(metadata[0]), str(metadata[1])) in self._KNOWN_SCHEMA_MIGRATIONS:
                cursor.execute(
                    "UPDATE runtime_schema_metadata "
                    "SET schema_version=%s,schema_checksum=%s,adopted_at=now() "
                    "WHERE schema_name=%s",
                    (self.SCHEMA_VERSION, checksum, self.SCHEMA_NAME),
                )
            else:
                connection.rollback()
                raise SchemaAdoptionError(
                    self.SCHEMA_NAME,
                    checksum,
                    str(metadata[1]),
                )

            # Bootstrap only the explicit local profile. A caller-supplied context
            # is authentication input, never an authority-incarnation command.
            cursor.execute("LOCK TABLE authority_instances IN SHARE ROW EXCLUSIVE MODE")
            cursor.execute(
                "INSERT INTO authority_instances"
                "(authority_id,authority_incarnation,status) "
                "SELECT %s,%s,'active' "
                "WHERE NOT EXISTS (SELECT 1 FROM authority_instances)",
                self._authority_binding,
            )
            cursor.execute(
                "INSERT INTO scopes(scope_id,tenant_id,policy,status) "
                "VALUES ('local-scope',%s,'{}','active') "
                "ON CONFLICT DO NOTHING",
                (self.context.tenant_id,),
            )
            cursor.execute(
                "INSERT INTO agent_slots(agent_slot_id,tenant_id,scope_id,status) "
                "VALUES ('local-slot',%s,'local-scope','active') "
                "ON CONFLICT DO NOTHING",
                (self.context.tenant_id,),
            )

    def bootstrap_local_grant(
        self,
        permissions: tuple[str, ...] = (
            "work_item.create",
            "work_item.transition",
            "evidence.record",
            "review.assign",
            "review.record",
            "acceptance.finalize",
            "lease.acquire",
            "lease.renew",
            "lease.release",
            "lease.revoke",
            "effect.write",
            "work_item.read",
        ),
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO grants("
                "grant_ref,tenant_id,principal_ref,authority_id,"
                "authority_incarnation,scope_id,permissions,expires_at,revoked_at) "
                "VALUES (%s,%s,%s,%s,%s,'local-scope',%s,"
                "now()+interval '365 days',NULL) "
                "ON CONFLICT (grant_ref) DO UPDATE SET "
                "tenant_id=EXCLUDED.tenant_id,"
                "principal_ref=EXCLUDED.principal_ref,"
                "authority_id=EXCLUDED.authority_id,"
                "authority_incarnation=EXCLUDED.authority_incarnation,"
                "scope_id=EXCLUDED.scope_id,"
                "permissions=EXCLUDED.permissions,"
                "expires_at=EXCLUDED.expires_at,"
                "revoked_at=NULL",
                (
                    self.context.grant_ref,
                    self.context.tenant_id,
                    self.context.principal_ref,
                    self.context.authority_id,
                    self.context.authority_incarnation,
                    json.dumps(permissions),
                ),
            )

    def _authorize(
        self,
        command: CommandEnvelope,
        cursor: psycopg.Cursor | None = None,
        permission: str = "work_item.read",
        scope_id: str | None = None,
    ) -> None:
        if cursor is None:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        now = datetime.now(UTC)
        current = self.context

        if (
            command.issued_at.tzinfo is None
            or command.deadline.tzinfo is None
            or command.deadline <= now
            or command.issued_at > now
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        if (
            command.tenant_id,
            command.authority_id,
            command.authority_incarnation,
            command.principal_ref,
            command.grant_ref,
        ) != (
            current.tenant_id,
            current.authority_id,
            current.authority_incarnation,
            current.principal_ref,
            current.grant_ref,
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

        self._lock_command_identity(cursor, command)
        cursor.execute(
            "SELECT g.scope_id,g.permissions,g.expires_at "
            "FROM grants g "
            "JOIN authority_instances a "
            "ON a.authority_id=g.authority_id "
            "AND a.authority_incarnation=g.authority_incarnation "
            "JOIN scopes s ON s.scope_id=g.scope_id "
            "WHERE g.grant_ref=%s "
            "AND g.tenant_id=%s "
            "AND g.principal_ref=%s "
            "AND g.authority_id=%s "
            "AND g.authority_incarnation=%s "
            "AND a.status='active' "
            "AND (SELECT count(*) FROM authority_instances current_authority "
            "WHERE current_authority.authority_id=g.authority_id "
            "AND current_authority.status='active')=1 "
            "AND s.tenant_id=%s "
            "AND s.status='active' "
            "AND g.revoked_at IS NULL "
            "AND g.expires_at>%s FOR UPDATE",
            (
                current.grant_ref,
                current.tenant_id,
                current.principal_ref,
                current.authority_id,
                current.authority_incarnation,
                current.tenant_id,
                now,
            ),
        )
        row = cursor.fetchone()

        if (
            row is None
            or command.deadline <= datetime.now(UTC)
            or row[2] <= datetime.now(UTC)
            or permission not in tuple(row[1] or ())
            or (scope_id is not None and str(row[0]) != str(scope_id))
        ):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)

    @staticmethod
    def _hash(command: CommandEnvelope, extra: Mapping[str, object]) -> str:
        return command.canonical_hash(extra)

    def _dedup(
        self,
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        result: CommandResult,
        extra: Mapping[str, object],
    ) -> tuple[CommandResult | None, str]:
        digest = self._hash(command, extra)
        self._lock_command_identity(cursor, command)
        cursor.execute(
            "SELECT idempotency_key,command_id,payload_hash,hash_version,"
            "canonical_hash,migration_state,replay_policy,result_json,legacy_record "
            "FROM command_dedup WHERE tenant_id=%s AND ("
            "idempotency_key=%s OR command_id=%s OR legacy_command_id=%s "
            "OR legacy_record ->> 'command_id'=%s "
            "OR legacy_record -> 'result_json' ->> 'command_id'=%s) "
            "ORDER BY idempotency_key FOR UPDATE",
            (command.tenant_id, command.idempotency_key, command.command_id,
             command.command_id, command.command_id, command.command_id),
        )
        rows = cursor.fetchall()
        if rows:
            # Matching one key does not erase another row's historical claim.
            if len(rows) != 1:
                raise IdempotencyConflict(command.idempotency_key)
            row = rows[0]
            if row[0] != command.idempotency_key or row[5] == "quarantined" or row[6] == "quarantine":
                raise IdempotencyConflict(command.idempotency_key)
            if row[5] == "current":
                if (row[1] != command.command_id or row[3] != "v2"
                        or row[6] != "replay_safe" or row[4] != digest or row[2] != digest):
                    raise IdempotencyConflict(command.idempotency_key)
            else:
                if row[5] not in ("legacy", "migrated") or row[6] != "verify_legacy_hash":
                    raise IdempotencyConflict(command.idempotency_key)
                original = row[8] if isinstance(row[8], Mapping) else {
                    "tenant_id": command.tenant_id, "idempotency_key": row[0],
                    "command_id": row[1], "payload_hash": row[2],
                    "hash_version": row[3], "result_json": row[7],
                }
                # The historical event is trusted database provenance; no field
                # in the retry body supplies or repairs the historical principal.
                cursor.execute(
                    "SELECT DISTINCT initiated_by FROM domain_events "
                    "WHERE tenant_id=%s AND command_id=%s AND work_item_id=%s "
                    "AND lineage_mode='external_command'",
                    (command.tenant_id, command.command_id, command.target_id),
                )
                principals = cursor.fetchall()
                if len(principals) > 1:
                    raise IdempotencyConflict(command.idempotency_key)
                record = LegacyCommandRecord(
                    tenant_id=original.get("tenant_id"),
                    idempotency_key=original.get("idempotency_key"),
                    command_id=original.get("command_id"),
                    payload_hash=original.get("payload_hash"),
                    result_json=original.get("result_json"),
                    hash_version=original.get("hash_version"),
                    principal_ref=principals[0][0] if principals else None,
                )
                decision = classify_replay(record, command, extra=extra)
                if decision.action != "replay":
                    raise IdempotencyConflict(command.idempotency_key)
            try:
                replay = CommandResult.model_validate(row[7])
            except (TypeError, ValueError):
                raise IdempotencyConflict(command.idempotency_key) from None
            if replay.command_id != command.command_id or replay.target_id != command.target_id:
                raise IdempotencyConflict(command.idempotency_key)
            return replay.model_copy(update={"duplicate": True}), digest

        if command.hash_version != "v2":
            raise IdempotencyConflict(command.idempotency_key)
        cursor.execute(
            "INSERT INTO command_dedup("
            "tenant_id,idempotency_key,command_id,payload_hash,hash_version,"
            "canonical_hash,migration_state,replay_policy,result_json) "
            "VALUES (%s,%s,%s,%s,'v2',%s,'current','replay_safe',%s)",
            (command.tenant_id, command.idempotency_key, command.command_id,
             digest, digest, result.model_dump_json()),
        )
        return None, digest

    def _lock_work_item(
        self,
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        work_item_id: str,
        *,
        permission: str,
    ) -> tuple[Any, ...]:
        self._authorize(command, cursor, permission)
        cursor.execute(
            "SELECT scope_id,state,revision,source_baseline,created_by,agent_slot_id "
            "FROM work_items "
            "WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
            (self.context.tenant_id, work_item_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise NotFound("work_item", work_item_id)

        self._authorize(command, cursor, permission, str(row[0]))

        return row

    @staticmethod
    def _evidence_set_hash(refs: Iterable[str]) -> str:
        return hashlib.sha256(
            json.dumps(
                sorted(set(refs)),
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def create_work_item(
        self,
        command: CommandEnvelope,
        scope_id: str,
        agent_slot_id: str,
        source_baseline: str,
    ) -> CommandResult:
        self._expect_command(command, 'work_item.create')
        result = CommandResult(
            command_id=command.command_id,
            operation_id=f"op-{uuid.uuid4()}",
            target_id=command.target_id,
            revision=0,
            state=WorkItemState.CANDIDATE,
        )

        with self._connect() as connection, connection.cursor() as cursor:
            self._authorize(command, cursor, "work_item.create", scope_id)

            duplicate, digest = self._dedup(
                cursor,
                command,
                result,
                {
                    "scope_id": scope_id,
                    "agent_slot_id": agent_slot_id,
                    "source_baseline": source_baseline,
                },
            )
            if duplicate is not None:
                return duplicate

            if command.expected_revision != 0:
                raise RevisionConflict(command.target_id, command.expected_revision, 0)

            cursor.execute(
                "SELECT 1 FROM scopes s "
                "JOIN agent_slots a ON a.scope_id=s.scope_id "
                "WHERE s.scope_id=%s "
                "AND a.agent_slot_id=%s "
                "AND s.tenant_id=%s "
                "AND a.tenant_id=%s "
                "AND s.status='active' "
                "AND a.status='active'",
                (
                    scope_id,
                    agent_slot_id,
                    self.context.tenant_id,
                    self.context.tenant_id,
                ),
            )
            if cursor.fetchone() is None:
                raise AuthorizationDenied(
                    command.principal_ref,
                    command.grant_ref,
                )

            cursor.execute(
                "INSERT INTO work_items("
                "work_item_id,tenant_id,scope_id,agent_slot_id,state,"
                "execution_status,source_baseline,created_by) "
                "VALUES (%s,%s,%s,%s,'candidate','ready',%s,%s)",
                (
                    command.target_id,
                    self.context.tenant_id,
                    scope_id,
                    agent_slot_id,
                    source_baseline,
                    self.context.principal_ref,
                ),
            )

            self._record(
                cursor,
                command,
                None,
                WorkItemState.CANDIDATE,
                0,
                (),
                digest,
            )
            self._operation(cursor, command, result.operation_id)
            self._outbox(
                cursor,
                command,
                result.operation_id,
                "work_item.created",
                {"state": "candidate"},
            )

        return result

    def transition_work_item(
        self,
        command: CommandEnvelope,
        transition: TransitionRequest,
    ) -> CommandResult:
        self._expect_command(command, 'work_item.transition')
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT scope_id FROM work_items "
                "WHERE tenant_id=%s AND work_item_id=%s",
                (self.context.tenant_id, command.target_id),
            )
            scope = cursor.fetchone()
            if scope is None:
                raise NotFound("work_item", command.target_id)

            self._authorize(
                command,
                cursor,
                "work_item.transition",
                str(scope[0]),
            )
            if transition.to_state is WorkItemState.ACCEPTED:
                self._authorize(command, cursor, "acceptance.finalize", str(scope[0]))

            result = CommandResult(
                command_id=command.command_id,
                operation_id=f"op-{uuid.uuid4()}",
                target_id=command.target_id,
                revision=command.expected_revision + 1,
                state=transition.to_state,
            )
            duplicate, digest = self._dedup(
                cursor,
                command,
                result,
                {"transition": transition.model_dump(mode="json")},
            )
            if duplicate is not None:
                return duplicate

            cursor.execute(
                "SELECT state,revision,source_baseline,scope_id "
                "FROM work_items "
                "WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
                (self.context.tenant_id, command.target_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise NotFound("work_item", command.target_id)

            current = WorkItemState(row[0])
            revision = int(row[1])
            if revision != command.expected_revision:
                raise RevisionConflict(
                    command.target_id,
                    command.expected_revision,
                    revision,
                )

            acceptance_metadata = self._guard(
                cursor,
                command,
                current,
                transition,
                str(row[2]),
                str(row[3]),
            )

            next_revision = revision + 1
            cursor.execute(
                "UPDATE work_items "
                "SET state=%s,revision=%s,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND work_item_id=%s AND clock_timestamp()<%s",
                (
                    transition.to_state,
                    next_revision,
                    self.context.tenant_id,
                    command.target_id,
                    acceptance_metadata["valid_until"],
                ),
            )
            if cursor.rowcount != 1:
                raise AcceptanceGuardFailed("acceptance authorization expired during verification")

            refs = (
                transition.evidence_refs
                + transition.effect_refs
                + transition.readback_refs
            )
            self._record(
                cursor,
                command,
                current,
                transition.to_state,
                next_revision,
                refs,
                digest,
            )

            if transition.to_state is WorkItemState.ACCEPTANCE_READY:
                cursor.execute(
                    "INSERT INTO accepted_state_revisions("
                    "tenant_id,work_item_id,revision,baseline_ref,evidence_refs,"
                    "review_ref,effect_refs,readback_refs,accepted_by,policy_version,"
                    "parent_revision,scope_id,valid_from,candidate_ref,"
                    "evidence_bundle_refs,policy_digest,readback_digest,"
                    "unresolved_items,readiness_snapshot) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,now(),"
                    "%s,%s,%s,%s,%s,TRUE)",
                    (
                        self.context.tenant_id,
                        command.target_id,
                        next_revision,
                        row[2],
                        json.dumps(transition.evidence_refs),
                        transition.review_ref,
                        json.dumps(transition.effect_refs),
                        json.dumps(transition.readback_refs),
                        "sha256:" + acceptance_metadata["policy_digest"],
                        revision,
                        row[3],
                        acceptance_metadata["candidate_ref"],
                        json.dumps(acceptance_metadata["evidence_bundle_refs"]),
                        acceptance_metadata["policy_digest"],
                        acceptance_metadata["readback_digest"],
                        json.dumps([]),
                    ),
                )

            elif transition.to_state is WorkItemState.ACCEPTED:
                cursor.execute(
                    "INSERT INTO accepted_state_revisions("
                    "tenant_id,work_item_id,revision,baseline_ref,evidence_refs,"
                    "review_ref,effect_refs,readback_refs,accepted_by,policy_version,"
                    "parent_revision,scope_id,valid_from,candidate_ref,"
                    "evidence_bundle_refs,policy_digest,readback_digest,"
                    "unresolved_items,readiness_snapshot) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),"
                    "%s,%s,%s,%s,%s,FALSE)",
                    (
                        self.context.tenant_id,
                        command.target_id,
                        next_revision,
                        row[2],
                        json.dumps(transition.evidence_refs),
                        transition.review_ref,
                        json.dumps(transition.effect_refs),
                        json.dumps(transition.readback_refs),
                        self.context.principal_ref,
                        "sha256:" + acceptance_metadata["policy_digest"],
                        revision,
                        row[3],
                        acceptance_metadata["candidate_ref"],
                        json.dumps(acceptance_metadata["evidence_bundle_refs"]),
                        acceptance_metadata["policy_digest"],
                        acceptance_metadata["readback_digest"],
                        json.dumps([]),
                    ),
                )

            self._operation(cursor, command, result.operation_id)
            self._outbox(
                cursor,
                command,
                result.operation_id,
                f"work_item.{transition.to_state}",
                {"state": str(transition.to_state)},
            )
            return result.model_copy(update={"revision": next_revision})

    def _verify_artifact_refs(self, value: object, scope_id: str) -> bool:
        if not value or self._artifact_store is None:
            return False

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return False

        if not isinstance(value, (list, tuple)):
            return False

        try:
            for item in value:
                ref = ArtifactRef.model_validate(item)
                if ref.scope_id != scope_id:
                    return False
                self._artifact_store.verify(ref)
        except (AttributeError, OSError, TypeError, ValueError):
            return False

        return True

    @staticmethod
    def _json_candidate(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value:
                return value
            if isinstance(value, Mapping):
                candidate = value.get("candidate_ref")
                if isinstance(candidate, str) and candidate:
                    return candidate
        return None

    @staticmethod
    def _same_refs(left: object, right: object) -> bool:
        try:
            return {
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in (left or [])
            } == {
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in (right or [])
            }
        except (TypeError, ValueError):
            return False


    def _guard(
        self, cursor: psycopg.Cursor, command: CommandEnvelope, current: WorkItemState,
        transition: TransitionRequest, baseline: str, scope_id: str,
    ) -> dict[str, Any]:
        ready = current is WorkItemState.CANDIDATE and transition.to_state is WorkItemState.ACCEPTANCE_READY
        accepted = current is WorkItemState.ACCEPTANCE_READY and transition.to_state is WorkItemState.ACCEPTED
        if not ready and not accepted:
            raise InvalidTransition(current, transition.to_state)
        if len(transition.evidence_refs) != 1 or transition.review_ref is None:
            raise AcceptanceGuardFailed("exactly one evidence and its assigned review are required")
        cursor.execute(
            "SELECT to_jsonb(e),to_jsonb(b) FROM evidence e JOIN evidence_bundles b "
            "ON b.evidence_id=e.evidence_id AND b.tenant_id=e.tenant_id AND b.work_item_id=e.work_item_id "
            "WHERE e.tenant_id=%s AND e.work_item_id=%s AND e.evidence_id=ANY(%s) FOR UPDATE OF e,b",
            (self.tenant_id, command.target_id, list(transition.evidence_refs)),
        )
        rows = cursor.fetchall()
        if len(rows) != len(transition.evidence_refs):
            raise AcceptanceGuardFailed("complete evidence bundle set is missing")
        candidates: set[str] = set()
        participants: set[str] = set()
        bundle_ids: list[str] = []
        bundle_digests: list[str] = []
        artifact_readbacks: list[dict[str, Any]] = []
        valid_until = [command.deadline]
        for stored_evidence, stored_bundle in rows:
            model_fields = EvidenceRecord.model_fields
            evidence = self._typed_evidence(
                EvidenceRecord, {key: value for key, value in stored_evidence.items() if key in model_fields},
                "stored evidence is invalid")
            bundle, receipt, bound = self._validate_bundle(
                cursor, evidence, stored_bundle["bundle_json"], command.target_id, baseline, scope_id)
            valid_until.extend((bound["producer_expires_at"], bound["observer_expires_at"]))
            if bundle.expires_at is not None:
                valid_until.append(bundle.expires_at)
            if (stored_evidence["scope_id"] != scope_id
                    or stored_bundle["bundle_id"] != evidence.bundle_ref
                    or stored_bundle["receipt_id"] != receipt.receipt_id
                    or stored_bundle["baseline_ref"] != baseline
                    or stored_bundle["producer_ref"] != bound["producer_ref"]
                    or stored_bundle["observer_ref"] != bound["observer_ref"]
                    or stored_bundle["source_class"] != bundle.source_class
                    or stored_bundle["evidence_state"] != bundle.evidence_state
                    or not self._same_refs(stored_bundle["artifact_refs"], [r.model_dump(mode="json") for r in bundle.artifact_refs])
                    or not self._same_refs(stored_bundle["readback_refs"], [r.model_dump(mode="json") for r in bundle.readback_refs])):
                raise AcceptanceGuardFailed("stored evidence bundle binding differs")
            candidates.add(bundle.candidate_ref)
            participants.update((bound["producer_ref"], bound["observer_ref"]))
            bundle_ids.append(bundle.evidence_id)
            bundle_digests.append(self._evidence_digest(bundle.model_dump(mode="json")))
            artifact_readbacks.extend(ref.model_dump(mode="json") for ref in receipt.readback_refs)
        if len(candidates) != 1:
            raise AcceptanceGuardFailed("evidence set must bind one candidate")
        if command.principal_ref in participants:
            raise AcceptanceGuardFailed("producer/observer cannot authorize acceptance")
        cursor.execute(
            "SELECT r.reviewer_ref,r.authority_incarnation,r.assignment_revision,a.assignment_revision,"
            "a.authority_incarnation,g.permissions,r.candidate_ref,r.evidence_set_hash,g.expires_at "
            "FROM reviews r JOIN reviewer_assignments a ON a.tenant_id=r.tenant_id "
            "AND a.work_item_id=r.work_item_id AND a.reviewer_ref=r.reviewer_ref "
            "AND a.reviewer_grant_ref=r.reviewer_grant_ref AND a.status='active' "
            "JOIN grants g ON g.grant_ref=r.reviewer_grant_ref AND g.tenant_id=r.tenant_id "
            "AND g.principal_ref=r.reviewer_ref AND g.scope_id=a.scope_id "
            "JOIN authority_instances ai ON ai.authority_id=g.authority_id "
            "AND ai.authority_incarnation=g.authority_incarnation "
            "JOIN scopes s ON s.scope_id=a.scope_id AND s.tenant_id=a.tenant_id "
            "WHERE r.tenant_id=%s AND r.work_item_id=%s AND r.review_id=%s AND r.verdict='pass' "
            "AND r.baseline_ref=%s AND r.evidence_ref=ANY(%s) AND a.scope_id=%s "
            "AND g.authority_id=%s AND g.authority_incarnation=%s "
            "AND r.authority_incarnation=g.authority_incarnation "
            "AND ai.status='active' AND s.status='active' "
            "AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() "
            "FOR UPDATE OF r,a,g,ai,s",
            (self.tenant_id, command.target_id, transition.review_ref, baseline,
             list(transition.evidence_refs), scope_id, self.authority_id, self.context.authority_incarnation),
        )
        review = cursor.fetchone()
        if review is None:
            raise AcceptanceGuardFailed("independent assigned authorized review is missing")
        if (review[0] in participants or review[1] != review[4] or review[2] != review[3]
                or "review.record" not in tuple(review[5] or ()) or review[6] not in candidates
                or review[7] != self._evidence_set_hash(transition.evidence_refs)):
            raise AcceptanceGuardFailed("reviewer independence or evidence binding failed")
        valid_until.append(review[8])
        candidate_ref = next(iter(candidates))
        # WorkItem is already locked by transition_work_item. Effect admission
        # must take the same lock before inserting/updating any Effect, and must
        # reject mutation once accepted. The schema trigger enforces this barrier
        # even for an admission path which has not yet adopted the protocol.
        readbacks = self._validate_acceptance_effects(
            cursor, command, transition, baseline, scope_id, candidate_ref)
        cursor.execute(
            "SELECT s.policy,g.expires_at FROM scopes s JOIN grants g "
            "ON g.scope_id=s.scope_id AND g.tenant_id=s.tenant_id "
            "WHERE s.tenant_id=%s AND s.scope_id=%s AND g.grant_ref=%s "
            "AND g.principal_ref=%s AND g.authority_id=%s AND g.authority_incarnation=%s "
            "FOR UPDATE OF s,g",
            (self.tenant_id, scope_id, self.context.grant_ref, self.context.principal_ref,
             self.authority_id, self.context.authority_incarnation),
        )
        policy = cursor.fetchone()
        if policy is None:
            raise AcceptanceGuardFailed("acceptance authorizer binding is missing")
        valid_until.append(policy[1])
        source_readbacks = {
            "baseline_ref": baseline,
            "candidate_ref": candidate_ref,
            "bundle_digests": sorted(bundle_digests),
            "review": {
                "review_ref": transition.review_ref,
                "reviewer_ref": review[0],
                "authority_incarnation": review[1],
                "assignment_revision": review[2],
                "candidate_ref": review[6],
                "evidence_set_hash": review[7],
            },
            "artifacts": sorted(artifact_readbacks, key=lambda value: self._evidence_digest(value)),
        }
        source_readback_digest = self._evidence_digest(source_readbacks)
        metadata = {
            "candidate_ref": candidate_ref, "evidence_bundle_refs": sorted(bundle_ids),
            "policy_digest": self._evidence_digest({"scope_id": scope_id, "policy": policy[0], "version": "1"}),
            "source_readback_digest": source_readback_digest,
            # transition_work_item must enforce this in its state UPDATE using
            # clock_timestamp() < valid_until and require exactly one updated
            # row. This catches time elapsed during CAS/live readback without
            # another verification pass or a SELECT-to-UPDATE time race.
            "valid_until": min(valid_until),
            # Readiness authorizes subsequent publication. Its source readback
            # seal must not freeze the later publication Effect universe.
            "readback_digest": source_readback_digest if ready else self._evidence_digest({
                "source_readback_digest": source_readback_digest, "effects": readbacks}),
        }
        if accepted:
            cursor.execute(
                "SELECT revision,baseline_ref,evidence_refs,review_ref,effect_refs,readback_refs,scope_id,"
                "candidate_ref,evidence_bundle_refs,policy_digest,readback_digest,unresolved_items "
                "FROM accepted_state_revisions WHERE tenant_id=%s AND work_item_id=%s "
                "AND readiness_snapshot=TRUE ORDER BY revision DESC LIMIT 1 FOR UPDATE",
                (self.tenant_id, command.target_id),
            )
            snapshot = cursor.fetchone()
            if (snapshot is None or snapshot[0] != command.expected_revision or snapshot[1] != baseline
                    or not self._same_refs(snapshot[2], transition.evidence_refs)
                    or snapshot[3] != transition.review_ref
                    or not set(snapshot[4] or ()).issubset(set(transition.effect_refs))
                    or snapshot[6] != scope_id or snapshot[7] != metadata["candidate_ref"]
                    or not self._same_refs(snapshot[8], metadata["evidence_bundle_refs"])
                    or snapshot[9] != metadata["policy_digest"] or snapshot[10] != source_readback_digest
                    or snapshot[11]):
                raise AcceptanceGuardFailed("readiness snapshot bindings changed")
        return metadata

    def _validate_bundle(
        self, cursor: psycopg.Cursor, evidence: EvidenceRecord, bundle: Any,
        work_item_id: str, baseline: str, scope_id: str,
    ) -> tuple[EvidenceBundle, ExecutionReceipt, dict[str, Any]]:
        evidence = self._typed_evidence(EvidenceRecord, evidence, "invalid typed evidence record")
        bundle = self._typed_evidence(EvidenceBundle, bundle, "invalid typed evidence bundle")
        receipt = bundle.execution_receipt
        if (not bundle.is_complete or not receipt.is_complete
                or evidence.evidence_state != "complete" or evidence.source_class != "directly_verified"
                or bundle.observed_at.tzinfo is None or bundle.observed_at > datetime.now(UTC)
                or bundle.observed_at < receipt.observed_at
                or (bundle.expires_at is not None and (
                    bundle.expires_at.tzinfo is None or bundle.expires_at <= datetime.now(UTC)))):
            raise AcceptanceGuardFailed("complete typed evidence bundle required")
        identity = (
            bundle.evidence_id == evidence.evidence_id == evidence.bundle_ref,
            bundle.work_item_id == receipt.work_item_id == evidence.work_item_id == work_item_id,
            bundle.source_baseline == receipt.source_baseline == evidence.baseline_ref == baseline,
            bundle.candidate_ref == receipt.candidate_ref == evidence.candidate_ref,
            bundle.observer_ref == evidence.observer_ref,
            bundle.producer_ref == evidence.producer_ref,
            evidence.execution_receipt_ref == receipt.receipt_id,
            evidence.attempt_id == receipt.attempt_id,
            bundle.command_id == receipt.command_id,
            bundle.operation_id == receipt.operation_id,
            bundle.event_id == receipt.event_id,
            evidence.test_exit_code == 0,
        )
        if not all(identity):
            raise AcceptanceGuardFailed("bundle/receipt identity mismatch")
        # Optional EvidenceRecord lineage fields refer to evidence submission;
        # the authoritative values are assigned by record_evidence below.
        bound = self._execution_binding(cursor, receipt, scope_id)
        if bundle.producer_ref != bound["producer_ref"] or bundle.observer_ref != bound["observer_ref"]:
            raise AcceptanceGuardFailed("bundle producer/observer differs from trusted execution")
        cursor.execute(
            "SELECT execution_id,attempt_id,producer_ref,agent_slot_id,source_baseline,source_class,"
            "finished_at,exit_code,os_name,toolchain,command_line,artifact_refs,readback_refs,"
            "output_artifact_ref,receipt_json,started_at FROM execution_receipts "
            "WHERE tenant_id=%s AND work_item_id=%s AND receipt_id=%s FOR UPDATE",
            (self.tenant_id, work_item_id, receipt.receipt_id),
        )
        stored = cursor.fetchone()
        if stored is None:
            raise AcceptanceGuardFailed("trusted execution receipt is not registered")
        stored_receipt = self._typed_evidence(ExecutionReceipt, stored[14], "registered receipt is invalid")
        if (stored_receipt.model_dump(mode="json") != receipt.model_dump(mode="json")
                or stored[0] != receipt.operation_id or stored[1] != receipt.attempt_id
                or stored[2] != bound["producer_ref"] or stored[3] != bound["agent_slot_id"]
                or stored[4] != baseline or stored[5] != "directly_verified"
                or stored[6] != receipt.observed_at or stored[15] != bound["execution_started_at"]
                or stored[7] != 0 or stored[8] != receipt.os
                or stored[9] != receipt.toolchain or list(stored[10]) != list(receipt.test_commands)
                or stored[13] != receipt.candidate_ref):
            raise AcceptanceGuardFailed("receipt differs from registered execution receipt")
        artifacts = [ref.model_dump(mode="json") for ref in receipt.artifact_refs]
        readbacks = [ref.model_dump(mode="json") for ref in receipt.readback_refs]
        for refs in (bundle.artifact_refs, evidence.artifact_refs):
            if len(refs) != len(artifacts) or not self._same_refs([ref.model_dump(mode="json") for ref in refs], artifacts):
                raise AcceptanceGuardFailed("bundle/receipt artifact sets differ")
        for refs in (bundle.readback_refs, evidence.readback_refs):
            if len(refs) != len(readbacks) or not self._same_refs([ref.model_dump(mode="json") for ref in refs], readbacks):
                raise AcceptanceGuardFailed("bundle/receipt readback sets differ")
        if not self._same_refs(stored[11], artifacts) or not self._same_refs(stored[12], readbacks):
            raise AcceptanceGuardFailed("registered receipt artifact sets differ")
        if evidence.artifact_sha256 not in {
            ref.sha256 for ref in receipt.artifact_refs if ref.kind == "output"
        }:
            raise AcceptanceGuardFailed("evidence digest does not bind candidate bytes")
        self._validate_execution_receipt(receipt, scope_id)
        self.enrollment.verify_receipt_provenance(cursor, receipt)
        return bundle, receipt, bound

    def record_evidence(
        self, command: CommandEnvelope, evidence: EvidenceRecord, bundle: Any | None = None,
    ) -> CommandResult:
        if command.command_type != "evidence.record" or command.target_kind != "work_item":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        evidence = self._typed_evidence(EvidenceRecord, evidence, "invalid typed evidence record")
        if bundle is not None:
            bundle = self._typed_evidence(EvidenceBundle, bundle, "invalid typed evidence bundle")
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != evidence.work_item_id:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            row = self._lock_work_item(cursor, command, evidence.work_item_id, permission="evidence.record")
            result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                                   target_id=evidence.work_item_id, revision=int(row[2]), state="evidence")
            extra = {"evidence": evidence.model_dump(mode="json"),
                     "bundle": bundle.model_dump(mode="json") if bundle is not None else None}
            duplicate, digest = self._dedup(cursor, command, result, extra)
            if duplicate is not None:
                return duplicate
            if command.expected_revision != int(row[2]):
                raise RevisionConflict(command.target_id, command.expected_revision, int(row[2]))
            if evidence.baseline_ref != str(row[3]):
                raise AcceptanceGuardFailed("evidence source baseline differs from work item")
            if bundle is not None:
                bundle, receipt, bound = self._validate_bundle(
                    cursor, evidence, bundle, command.target_id, str(row[3]), str(row[0]))
                producer = bound["producer_ref"]
            else:
                if (evidence.source_class == "directly_verified" or evidence.evidence_state != "incomplete"
                        or any((evidence.bundle_ref, evidence.execution_receipt_ref, evidence.attempt_id))
                        or evidence.observer_ref != command.principal_ref
                        or evidence.producer_ref not in (None, command.principal_ref)):
                    raise AcceptanceGuardFailed("untrusted summary must remain an incomplete candidate")
                producer = command.principal_ref
            if (evidence.command_id not in (None, command.command_id)
                    or evidence.operation_id is not None or evidence.event_id is not None):
                raise AcceptanceGuardFailed("evidence submission lineage is authority assigned")
            cursor.execute(
                "INSERT INTO evidence(evidence_id,tenant_id,work_item_id,observer_ref,source_class,"
                "baseline_ref,artifact_sha256,summary,bundle_ref,candidate_ref,execution_receipt_ref,"
                "evidence_state,producer_ref,attempt_id,command_id,operation_id,test_exit_code,"
                "artifact_refs,readback_refs,scope_id) VALUES ("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (evidence.evidence_id, self.tenant_id, evidence.work_item_id, evidence.observer_ref,
                 evidence.source_class, evidence.baseline_ref, evidence.artifact_sha256, evidence.summary,
                 evidence.bundle_ref, evidence.candidate_ref, evidence.execution_receipt_ref,
                 evidence.evidence_state, producer, evidence.attempt_id, command.command_id,
                 result.operation_id, evidence.test_exit_code,
                 json.dumps([ref.model_dump(mode="json") for ref in evidence.artifact_refs]),
                 json.dumps([ref.model_dump(mode="json") for ref in evidence.readback_refs]), str(row[0])),
            )
            if bundle is not None:
                cursor.execute(
                    "INSERT INTO evidence_bundles(bundle_id,evidence_id,tenant_id,work_item_id,"
                    "baseline_ref,source_class,observer_ref,producer_ref,receipt_id,artifact_refs,"
                    "readback_refs,bundle_json,evidence_state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (bundle.evidence_id, evidence.evidence_id, self.tenant_id, bundle.work_item_id,
                     bundle.source_baseline, bundle.source_class, bound["observer_ref"], producer,
                     receipt.receipt_id,
                     json.dumps([ref.model_dump(mode="json") for ref in bundle.artifact_refs]),
                     json.dumps([ref.model_dump(mode="json") for ref in bundle.readback_refs]),
                     bundle.model_dump_json(), bundle.evidence_state),
                )
            self._record(cursor, command, WorkItemState(row[1]), WorkItemState(row[1]), int(row[2]),
                         (evidence.evidence_id,), digest)
            cursor.execute(
                "UPDATE evidence SET event_id=(SELECT event_id::text FROM domain_events "
                "WHERE tenant_id=%s AND command_id=%s AND work_item_id=%s ORDER BY event_id DESC LIMIT 1) "
                "WHERE tenant_id=%s AND evidence_id=%s",
                (self.tenant_id, command.command_id, command.target_id, self.tenant_id, evidence.evidence_id),
            )
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, "evidence.recorded",
                         {"evidence_id": evidence.evidence_id})
            return result

    def record_review(
        self,
        command: CommandEnvelope,
        review_id: str,
        work_item_id: str,
        verdict: str,
        evidence_ref: str,
        baseline_ref: str,
    ) -> CommandResult:
        self._expect_command(command, 'review.record')
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != work_item_id:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)

            row = self._lock_work_item(
                cursor,
                command,
                work_item_id,
                permission="review.record",
            )

            result = CommandResult(
                command_id=command.command_id,
                operation_id=f"op-{uuid.uuid4()}",
                target_id=work_item_id,
                revision=int(row[2]),
                state="review",
            )
            extra = {
                "review_id": review_id,
                "work_item_id": work_item_id,
                "verdict": verdict,
                "evidence_ref": evidence_ref,
                "baseline_ref": baseline_ref,
            }
            duplicate, digest = self._dedup(cursor, command, result, extra)
            if duplicate is not None:
                return duplicate

            if int(row[2]) != command.expected_revision:
                raise RevisionConflict(work_item_id, command.expected_revision, int(row[2]))

            cursor.execute(
                "SELECT baseline_ref,observer_ref,producer_ref,candidate_ref "
                "FROM evidence "
                "WHERE tenant_id=%s AND work_item_id=%s AND evidence_id=%s "
                "FOR UPDATE",
                (self.context.tenant_id, work_item_id, evidence_ref),
            )
            evidence = cursor.fetchone()
            if evidence is None or evidence[0] != baseline_ref:
                raise AcceptanceGuardFailed("review evidence is not bound")

            if command.principal_ref in {
                str(evidence[1]),
                str(evidence[2] or evidence[1]),
            }:
                raise AuthorizationDenied(
                    command.principal_ref,
                    command.grant_ref,
                )

            cursor.execute(
                "SELECT a.assignment_revision,a.authority_incarnation,g.permissions "
                "FROM reviewer_assignments a "
                "JOIN grants g ON g.grant_ref=a.reviewer_grant_ref "
                "AND g.tenant_id=a.tenant_id "
                "AND g.principal_ref=a.reviewer_ref "
                "AND g.scope_id=a.scope_id "
                "JOIN authority_instances ai "
                "ON ai.authority_id=g.authority_id "
                "AND ai.authority_incarnation=g.authority_incarnation "
                "AND ai.status='active' "
                "WHERE a.tenant_id=%s AND a.work_item_id=%s "
                "AND a.reviewer_ref=%s AND a.reviewer_grant_ref=%s "
                "AND a.status='active' "
                "AND a.authority_incarnation=g.authority_incarnation "
                "AND g.revoked_at IS NULL AND g.expires_at>now()",
                (
                    self.context.tenant_id,
                    work_item_id,
                    self.context.principal_ref,
                    self.context.grant_ref,
                ),
            )
            assignment = cursor.fetchone()
            if assignment is None or "review.record" not in tuple(
                assignment[2] or ()
            ):
                raise AuthorizationDenied(
                    self.context.principal_ref,
                    self.context.grant_ref,
                )

            cursor.execute(
                "INSERT INTO reviews("
                "review_id,tenant_id,work_item_id,reviewer_ref,reviewer_grant_ref,"
                "verdict,evidence_ref,baseline_ref,candidate_ref,evidence_set_hash,"
                "authority_incarnation,assignment_revision) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    review_id,
                    self.context.tenant_id,
                    work_item_id,
                    self.context.principal_ref,
                    self.context.grant_ref,
                    verdict,
                    evidence_ref,
                    baseline_ref,
                    evidence[3],
                    self._evidence_set_hash((evidence_ref,)),
                    self.context.authority_incarnation,
                    assignment[0],
                ),
            )
            self._record(
                cursor,
                command,
                WorkItemState(row[1]),
                WorkItemState(row[1]),
                int(row[2]),
                (review_id, evidence_ref),
                digest,
            )
            self._operation(cursor, command, result.operation_id)
            self._outbox(
                cursor,
                command,
                result.operation_id,
                "review.recorded",
                {"review_id": review_id, "evidence_id": evidence_ref},
            )
            return result

    def assign_reviewer(
        self,
        command: CommandEnvelope,
        work_item_id: str,
        reviewer_ref: str,
        reviewer_grant_ref: str,
    ) -> CommandResult:
        self._expect_command(command, 'review.assign')
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != work_item_id:
                raise AuthorizationDenied(
                    command.principal_ref,
                    command.grant_ref,
                )

            row = self._lock_work_item(
                cursor,
                command,
                work_item_id,
                permission="review.assign",
            )

            result = CommandResult(
                command_id=command.command_id,
                operation_id=f"op-{uuid.uuid4()}",
                target_id=work_item_id,
                revision=int(row[2]),
                state="reviewer_assignment",
            )
            extra = {
                "work_item_id": work_item_id,
                "reviewer_ref": reviewer_ref,
                "reviewer_grant_ref": reviewer_grant_ref,
            }
            duplicate, digest = self._dedup(cursor, command, result, extra)
            if duplicate is not None:
                return duplicate

            if int(row[2]) != command.expected_revision:
                raise RevisionConflict(work_item_id, command.expected_revision, int(row[2]))

            if reviewer_ref in {str(row[4]), self.context.principal_ref}:
                raise AuthorizationDenied(reviewer_ref, reviewer_grant_ref)

            cursor.execute(
                "SELECT 1 FROM evidence "
                "WHERE tenant_id=%s AND work_item_id=%s "
                "AND (observer_ref=%s OR producer_ref=%s)",
                (
                    self.context.tenant_id,
                    work_item_id,
                    reviewer_ref,
                    reviewer_ref,
                ),
            )
            if cursor.fetchone() is not None:
                raise AuthorizationDenied(reviewer_ref, reviewer_grant_ref)

            cursor.execute(
                "SELECT 1 FROM grants g "
                "JOIN authority_instances a "
                "ON a.authority_id=g.authority_id "
                "AND a.authority_incarnation=g.authority_incarnation "
                "WHERE g.grant_ref=%s "
                "AND g.tenant_id=%s "
                "AND g.principal_ref=%s "
                "AND g.scope_id=%s "
                "AND g.authority_id=%s "
                "AND g.authority_incarnation=%s "
                "AND a.status='active' "
                "AND g.revoked_at IS NULL "
                "AND g.expires_at>now()",
                (
                    reviewer_grant_ref,
                    self.context.tenant_id,
                    reviewer_ref,
                    row[0],
                    self.context.authority_id,
                    self.context.authority_incarnation,
                ),
            )
            if cursor.fetchone() is None:
                raise AuthorizationDenied(reviewer_ref, reviewer_grant_ref)

            cursor.execute(
                "SELECT COALESCE(MAX(assignment_revision),0) "
                "FROM reviewer_assignments "
                "WHERE tenant_id=%s AND work_item_id=%s",
                (self.context.tenant_id, work_item_id),
            )
            assignment_revision = int(cursor.fetchone()[0]) + 1

            cursor.execute(
                "INSERT INTO reviewer_assignments("
                "tenant_id,work_item_id,reviewer_ref,reviewer_grant_ref,assigned_by,"
                "scope_id,status,assignment_revision,command_id,operation_id,event_id,"
                "authority_incarnation,expected_work_item_revision) "
                "VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,NULL,%s,%s) "
                "ON CONFLICT (tenant_id,work_item_id,reviewer_ref) DO UPDATE SET "
                "reviewer_grant_ref=EXCLUDED.reviewer_grant_ref,"
                "assigned_by=EXCLUDED.assigned_by,"
                "scope_id=EXCLUDED.scope_id,status='active',"
                "assignment_revision=EXCLUDED.assignment_revision,"
                "command_id=EXCLUDED.command_id,"
                "operation_id=EXCLUDED.operation_id,"
                "authority_incarnation=EXCLUDED.authority_incarnation,"
                "expected_work_item_revision=EXCLUDED.expected_work_item_revision",
                (
                    self.context.tenant_id,
                    work_item_id,
                    reviewer_ref,
                    reviewer_grant_ref,
                    self.context.principal_ref,
                    row[0],
                    assignment_revision,
                    command.command_id,
                    result.operation_id,
                    self.context.authority_incarnation,
                    command.expected_revision,
                ),
            )
            self._record(
                cursor,
                command,
                WorkItemState(row[1]),
                WorkItemState(row[1]),
                int(row[2]),
                (reviewer_ref,),
                digest,
            )
            self._operation(cursor, command, result.operation_id)
            self._outbox(
                cursor,
                command,
                result.operation_id,
                "reviewer.assigned",
                {
                    "reviewer_ref": reviewer_ref,
                    "assignment_revision": str(assignment_revision),
                },
            )
            return result

    def get_work_item(
        self,
        work_item_id: str,
    ) -> dict[str, str | int] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT scope_id,work_item_id,state,execution_status,revision,"
                "source_baseline FROM work_items "
                "WHERE tenant_id=%s AND work_item_id=%s",
                (self.context.tenant_id, work_item_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            now = datetime.now(UTC)
            read = CommandEnvelope(
                command_id=f"read-{uuid.uuid4()}",
                command_type="work_item.read",
                idempotency_key=f"read-{uuid.uuid4()}",
                correlation_id="read",
                tenant_id=self.context.tenant_id,
                authority_id=self.context.authority_id,
                authority_incarnation=self.context.authority_incarnation,
                principal_ref=self.context.principal_ref,
                grant_ref=self.context.grant_ref,
                target_kind="work_item",
                target_id=work_item_id,
                expected_revision=0,
                issued_at=now,
                deadline=now + timedelta(minutes=1),
            )
            self._authorize(read, cursor, "work_item.read", str(row[0]))

            return {
                "work_item_id": row[1],
                "state": row[2],
                "execution_status": row[3],
                "revision": row[4],
                "source_baseline": row[5],
            }

    @staticmethod
    def _record(
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        before: WorkItemState | None,
        after: WorkItemState,
        revision: int,
        refs: Iterable[str],
        canonical_hash: str | None = None,
    ) -> None:
        cursor.execute(
            "INSERT INTO domain_events("
            "tenant_id,work_item_id,from_state,to_state,initiated_by,lineage_mode,"
            "command_id,resulting_revision,evidence_refs,command_hash_version,"
            "canonical_hash) "
            "VALUES (%s,%s,%s,%s,%s,'external_command',%s,%s,%s,%s,%s)",
            (
                command.tenant_id,
                command.target_id,
                before,
                after,
                command.principal_ref,
                command.command_id,
                revision,
                json.dumps(list(refs)),
                getattr(command, "hash_version", "v2"),
                canonical_hash or DomainAuthority._hash(command, {}),
            ),
        )

    @staticmethod
    def _operation(
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        operation_id: str,
    ) -> None:
        cursor.execute(
            "INSERT INTO operations("
            "operation_id,tenant_id,command_id,provider,provider_workflow_id,status) "
            "VALUES (%s,%s,%s,'temporal',%s,'committed')",
            (
                operation_id,
                command.tenant_id,
                command.command_id,
                f"acs-p1/{command.command_id}",
            ),
        )

    @staticmethod
    def _outbox(
        cursor: psycopg.Cursor,
        command: CommandEnvelope,
        operation_id: str,
        topic: str,
        payload: Mapping[str, str],
    ) -> None:
        cursor.execute(
            "INSERT INTO outbox(tenant_id,message_id,operation_id,topic,payload) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                command.tenant_id,
                f"msg-{command.command_id}",
                operation_id,
                topic,
                json.dumps(dict(payload)),
            ),
        )

    @staticmethod
    def _lock_command_identity(cursor: psycopg.Cursor, command: CommandEnvelope) -> None:
        # Distinct namespaces and JSON tuples avoid delimiter ambiguity. Sorting
        # the actual signed lock IDs also makes hash collisions deadlock-safe.
        identities = (
            ("acs-p1-command-id", command.tenant_id, command.command_id),
            ("acs-p1-idempotency-key", command.tenant_id, command.idempotency_key),
        )
        lock_ids = sorted({
            int.from_bytes(
                hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).digest()[:8],
                "big", signed=True,
            )
            for identity in identities
        })
        for lock_id in lock_ids:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))

    @staticmethod
    def _expect_command(command: CommandEnvelope, command_type: str) -> None:
        if command.command_type != command_type or command.target_kind != "work_item":
            raise ValueError("command_type/target_kind does not match the Domain method")

    @staticmethod
    def _typed_evidence(model: Any, value: Any, reason: str) -> Any:
        """Revalidate dumps: model_copy/model_construct bypass model validation."""
        try:
            data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            return model.model_validate_json(json.dumps(data), strict=True)
        except (TypeError, ValueError, AttributeError):
            raise AcceptanceGuardFailed(reason) from None

    @staticmethod
    def _evidence_digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _execution_binding(
        self, cursor: psycopg.Cursor, receipt: ExecutionReceipt, scope_id: str,
    ) -> dict[str, Any]:
        # These bindings are registered by the trusted Node admission path. This
        # module deliberately offers no caller-body API for creating an Attempt.
        cursor.execute(
            "SELECT a.producer_ref,a.runtime_id,a.observer_ref,a.observer_grant_ref,"
            "a.execution_command_id,a.execution_operation_id,a.execution_event_id,"
            "a.provider,a.source_baseline,a.source_commit,a.source_tree,a.candidate_ref,"
            "a.agent_slot_id,a.authority_id,a.authority_incarnation,a.grant_ref,"
            "a.execution_started_at,g.expires_at,og.expires_at,g.permissions,og.permissions "
            "FROM attempts a JOIN work_items w ON w.tenant_id=a.tenant_id "
            "AND w.work_item_id=a.work_item_id AND w.scope_id=a.scope_id "
            "AND w.agent_slot_id=a.agent_slot_id AND w.source_baseline=a.source_baseline "
            "JOIN agent_slots slot ON slot.agent_slot_id=a.agent_slot_id "
            "AND slot.tenant_id=a.tenant_id AND slot.scope_id=a.scope_id AND slot.status='active' "
            "JOIN grants g ON g.grant_ref=a.grant_ref AND g.tenant_id=a.tenant_id "
            "AND g.principal_ref=a.producer_ref AND g.scope_id=a.scope_id "
            "AND g.authority_id=a.authority_id AND g.authority_incarnation=a.authority_incarnation "
            "JOIN grants og ON og.grant_ref=a.observer_grant_ref AND og.tenant_id=a.tenant_id "
            "AND og.principal_ref=a.observer_ref AND og.scope_id=a.scope_id "
            "AND og.authority_id=a.authority_id AND og.authority_incarnation=a.authority_incarnation "
            "JOIN authority_instances ai ON ai.authority_id=a.authority_id "
            "AND ai.authority_incarnation=a.authority_incarnation "
            "JOIN scopes s ON s.scope_id=a.scope_id AND s.tenant_id=a.tenant_id "
            "WHERE a.attempt_id=%s AND a.tenant_id=%s AND a.work_item_id=%s "
            "AND a.scope_id=%s AND a.authority_id=%s AND a.authority_incarnation=%s "
            "AND ai.status='active' AND s.status='active' "
            "AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp() "
            "AND og.revoked_at IS NULL AND og.expires_at>clock_timestamp() "
            "FOR UPDATE OF a,w,g,og,ai,s,slot",
            (receipt.attempt_id, self.tenant_id, receipt.work_item_id, scope_id,
             self.authority_id, self.context.authority_incarnation),
        )
        row = cursor.fetchone()
        if row is None:
            raise AcceptanceGuardFailed("trusted execution attempt binding is missing or unauthorized")
        keys = ("producer_ref", "runtime_id", "observer_ref", "observer_grant_ref",
                "command_id", "operation_id", "event_id", "provider", "source_baseline",
                "source_commit", "source_tree", "candidate_ref", "agent_slot_id",
                "authority_id", "authority_incarnation", "producer_grant_ref",
                "execution_started_at", "producer_expires_at", "observer_expires_at",
                "producer_permissions", "observer_permissions")
        bound = dict(zip(keys, row, strict=True))
        if (any(not bound[key] for key in keys[:-2])
                or "execution.record" not in tuple(bound["observer_permissions"] or ())
                or "evidence.record" not in tuple(bound["producer_permissions"] or ())):
            raise AcceptanceGuardFailed("trusted execution attempt binding is missing or unauthorized")
        for key in ("runtime_id", "command_id", "operation_id", "event_id", "provider",
                    "source_baseline", "source_commit", "source_tree", "candidate_ref"):
            if getattr(receipt, key) != bound[key]:
                raise AcceptanceGuardFailed("receipt does not match trusted execution attempt")
        if receipt.observed_at.tzinfo is None or receipt.observed_at < bound["execution_started_at"]:
            raise AcceptanceGuardFailed("receipt observation precedes trusted execution")
        return bound

    def _validate_execution_receipt(
        self, receipt: ExecutionReceipt, scope_id: str,
    ) -> None:
        if (not receipt.is_complete or not receipt.readback_refs
                or receipt.observed_at.tzinfo is None
                or receipt.observed_at > datetime.now(UTC)):
            raise AcceptanceGuardFailed("complete successful execution receipt required")
        if not receipt.test_commands or len(receipt.test_commands) != len(receipt.test_exit_codes):
            raise AcceptanceGuardFailed("every test command must have exactly one exit code")
        if (any(type(code) is not int or code != 0 for code in receipt.test_exit_codes)
                or receipt.test_exit_code not in (None, 0)):
            raise AcceptanceGuardFailed("successful evidence requires zero test exits")
        for refs, label in ((receipt.artifact_refs, "artifact"), (receipt.readback_refs, "readback")):
            if (len({self._evidence_digest(ref.model_dump(mode="json")) for ref in refs}) != len(refs)
                    or any(not ref.immutable or ref.scope_id != scope_id for ref in refs)):
                raise AcceptanceGuardFailed("receipt contains duplicate/mutable/cross-scope artifact")
            if not self._verify_artifact_refs([ref.model_dump(mode="json") for ref in refs], scope_id):
                raise AcceptanceGuardFailed(f"receipt {label} bytes are not verified")
        source_refs = tuple(ref for ref in (receipt.source_diff, receipt.untracked_manifest) if ref is not None)
        if source_refs and not self._verify_artifact_refs(
            [ref.model_dump(mode="json") for ref in source_refs], scope_id
        ):
            raise AcceptanceGuardFailed("receipt source bytes are not verified")
        if not any(ref.kind == "output" for ref in receipt.artifact_refs):
            raise AcceptanceGuardFailed("receipt has no verified output artifact")

    def record_execution_receipt(
        self, command: CommandEnvelope, receipt: ExecutionReceipt, *, node_proof: Any | None = None,
    ) -> CommandResult:
        """Node-only receipt registration for an already trusted Attempt.

        execution.record is deliberately absent from bootstrap_local_grant.
        Receipt execution IDs are the registered execution lineage, whereas
        command/result/event belong to this registration transaction.
        """
        if command.command_type != "execution.record" or command.target_kind != "work_item":
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        receipt = self._typed_evidence(ExecutionReceipt, receipt, "invalid typed execution receipt")
        with self._connect() as connection, connection.cursor() as cursor:
            if command.target_id != receipt.work_item_id:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            row = self._lock_work_item(cursor, command, receipt.work_item_id, permission="execution.record")
            enrolled = self.enrollment.authorize_execution_receipt(cursor, command, receipt, node_proof)
            result = CommandResult(command_id=command.command_id, operation_id=f"op-{uuid.uuid4()}",
                                   target_id=receipt.work_item_id, revision=int(row[2]), state="execution_receipt")
            duplicate, digest = self._dedup(cursor, command, result, {"receipt": receipt.model_dump(mode="json")})
            if duplicate is not None:
                return duplicate
            enrolled = self.enrollment.validate_new_execution_receipt(cursor, command, receipt, enrolled)
            if command.expected_revision != int(row[2]):
                raise RevisionConflict(command.target_id, command.expected_revision, int(row[2]))
            bound = self._execution_binding(cursor, receipt, str(row[0]))
            if (command.principal_ref != bound["observer_ref"]
                    or command.grant_ref != bound["observer_grant_ref"]):
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            self._validate_execution_receipt(receipt, str(row[0]))
            cursor.execute(
                "INSERT INTO execution_receipts(receipt_id,execution_id,tenant_id,work_item_id,"
                "attempt_id,producer_ref,agent_slot_id,source_baseline,source_class,started_at,"
                "finished_at,exit_code,os_name,os_arch,toolchain,command_line,artifact_refs,"
                "readback_refs,output_artifact_ref,receipt_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'directly_verified',%s,%s,0,%s,'',%s,%s,%s,%s,%s,%s)",
                (receipt.receipt_id, receipt.operation_id, self.tenant_id, receipt.work_item_id,
                 receipt.attempt_id, bound["producer_ref"], bound["agent_slot_id"], receipt.source_baseline,
                 bound["execution_started_at"], receipt.observed_at, receipt.os, receipt.toolchain,
                 json.dumps(receipt.test_commands),
                 json.dumps([ref.model_dump(mode="json") for ref in receipt.artifact_refs]),
                 json.dumps([ref.model_dump(mode="json") for ref in receipt.readback_refs]),
                 receipt.candidate_ref, receipt.model_dump_json()),
            )
            self.enrollment.seal_execution_receipt(cursor, command, receipt, enrolled)
            self._record(cursor, command, WorkItemState(row[1]), WorkItemState(row[1]), int(row[2]),
                         (receipt.receipt_id,), digest)
            self._operation(cursor, command, result.operation_id)
            self._outbox(cursor, command, result.operation_id, "execution_receipt.recorded",
                         {"receipt_id": receipt.receipt_id})
            return result

    def _validate_acceptance_effects(
        self, cursor: psycopg.Cursor, command: CommandEnvelope, transition: TransitionRequest,
        baseline: str, scope_id: str, candidate_ref: str,
    ) -> list[dict[str, Any]]:
        cursor.execute(
            "SELECT effect_id,status,resource_id,baseline_ref,lease_id,fencing_token,generation,"
            "readback_ref,grant_ref,candidate_ref,operation_id,expected_sha256,expected_size_bytes,intent_sha256 "
            "FROM effects WHERE tenant_id=%s AND work_item_id=%s "
            "ORDER BY effect_id FOR UPDATE",
            (self.tenant_id, command.target_id),
        )
        rows = cursor.fetchall()
        if (len(set(transition.effect_refs)) != len(transition.effect_refs)
                or {row[0] for row in rows} != set(transition.effect_refs)):
            raise AcceptanceGuardFailed("all protected effects must be included")
        if len(transition.effect_refs) != len(transition.readback_refs):
            raise AcceptanceGuardFailed("every effect requires one readback reference")
        requested = dict(zip(transition.effect_refs, transition.readback_refs, strict=True))
        verifier = getattr(self, "_effect_readback_verifier", None)
        readbacks: list[dict[str, Any]] = []
        for row in rows:
            effect = dict(zip(("effect_id", "status", "resource_id", "baseline_ref", "lease_id",
                               "fencing_token", "generation", "readback_ref", "grant_ref", "candidate_ref",
                               "operation_id", "expected_sha256", "expected_size_bytes", "intent_sha256"), row, strict=True))
            if effect["status"] != "verified":
                raise AcceptanceGuardFailed("every protected effect must be verified")
            if effect["candidate_ref"] != candidate_ref:
                raise AcceptanceGuardFailed("effect candidate differs from readiness candidate")
            if (not effect["operation_id"] or not effect["expected_sha256"]
                    or effect["expected_size_bytes"] is None or not effect["intent_sha256"]):
                raise AcceptanceGuardFailed("effect execution proof binding is missing")
            if (effect["baseline_ref"] != baseline or not effect["readback_ref"]
                    or requested[effect["effect_id"]] != effect["readback_ref"]):
                raise AcceptanceGuardFailed("effect readback binding differs")
            # Preserve historical lease lineage but do not require a completed
            # effect to still hold its expired/released writer lease.
            cursor.execute(
                "SELECT g.principal_ref FROM leases l JOIN grants g ON g.grant_ref=l.grant_ref "
                "AND g.tenant_id=l.tenant_id AND g.authority_id=l.authority_id "
                "AND g.authority_incarnation=l.authority_incarnation "
                "WHERE l.tenant_id=%s AND l.lease_id=%s AND l.resource_id=%s "
                "AND l.fencing_token=%s AND l.generation=%s AND l.grant_ref=%s "
                "AND l.scope_id=%s AND g.scope_id=%s FOR UPDATE OF l,g",
                (self.tenant_id, effect["lease_id"], effect["resource_id"], effect["fencing_token"],
                 effect["generation"], effect["grant_ref"], scope_id, scope_id),
            )
            producer = cursor.fetchone()
            if producer is None:
                raise AcceptanceGuardFailed("effect producer lineage is missing")
            if producer[0] == command.principal_ref:
                raise AcceptanceGuardFailed("effect producer cannot authorize acceptance")
            if verifier is None:
                raise AcceptanceGuardFailed("live effect readback verifier is unavailable")
            effect.update(tenant_id=self.tenant_id, work_item_id=command.target_id, scope_id=scope_id,
                          producer_ref=producer[0])
            # The callback must perform actual gateway readback under these
            # locked DB bindings. Returning a cached DB status is insufficient.
            try:
                actual = self._typed_evidence(
                    EffectReadback, verifier(cursor, self.context, dict(effect)),
                    "live effect readback is invalid")
            except AcceptanceGuardFailed:
                raise
            except (OSError, RuntimeErrorBase, TypeError, ValueError):
                raise AcceptanceGuardFailed("live effect readback verification failed") from None
            if (actual.effect_id != effect["effect_id"] or actual.work_item_id != command.target_id
                    or actual.resource_id != effect["resource_id"] or actual.readback_ref != effect["readback_ref"]
                    or actual.operation_id != effect["operation_id"]
                    or actual.sha256 != effect["expected_sha256"]
                    or actual.size_bytes != effect["expected_size_bytes"]
                    or actual.intent_sha256 != effect["intent_sha256"]):
                raise AcceptanceGuardFailed("live effect readback binding differs")
            if (actual.completion_state != "completed" or not actual.completion_sha256
                    or len(actual.completion_sha256) != 64
                    or any(c not in "0123456789abcdef" for c in actual.completion_sha256)):
                raise AcceptanceGuardFailed("effect completion proof is missing or incomplete")
            readbacks.append(actual.model_dump(mode="json"))
        return readbacks
