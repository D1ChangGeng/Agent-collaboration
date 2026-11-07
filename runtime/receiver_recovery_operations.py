"""Durable authenticated receiver actions, separate from Message/Agent replies."""
from __future__ import annotations

import json
import uuid
from copy import copy
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime.auth import LocalCredentialAuthenticator
from runtime.communication_delivery_observer import CommunicationDeliveryObserver
from runtime.delivery import DeliveryDispatcher, DeliveryService
from runtime.errors import AuthorizationDenied, IdempotencyConflict, NotFound, RevisionConflict
from runtime.models import AuthenticatedContext, CommandEnvelope
from runtime.project_common import digest, handle

TOPIC = "communication.receiver.recovery"
FINAL = {"completed", "definitively_rejected", "unknown", "superseded", "cancelled_before_submit"}
READ_ACTIONS = {"inspect", "reconcile"}
LIFECYCLE_ACTIONS = {"prepare_receiver", "resume_receiver", "rebind_receiver"}
SELECTION_FIELDS = ("scope_id", "agent_slot_id", "machine_id", "node_id", "boot_incarnation")


@dataclass(frozen=True)
class OriginalRecoveryAuthority:
    authority: Any
    stored_command: CommandEnvelope
    admission_command: CommandEnvelope
    endpoint: dict
    actor_address: str


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    action: str
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2048)
    operation_ref: str | None = Field(default=None, min_length=1, max_length=512)
    target_endpoint_ref: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def action_requirements(self):
        if self.action not in {*READ_ACTIONS, "resume_receiver", "prepare_receiver", "rebind_receiver", "retry_delivery"}:
            raise ValueError("unsupported recovery action")
        if self.action in {"reconcile", "retry_delivery"} and self.operation_ref is None:
            raise ValueError("original operation_ref is required")
        if self.action == "rebind_receiver" and self.target_endpoint_ref is None:
            raise ValueError("target_endpoint_ref is required")
        if not self.reason.strip():
            raise ValueError("a recovery reason is required")
        return self


class ReceiverRecoveryOperations:
    def __init__(self, projects):
        self.projects = projects
        self.authority = projects.service.authority

    def _authorize(self, cursor, authority, project, receiver, request, *, lock_endpoint=True):
        name = "list_harnesses" if request.action in READ_ACTIONS else "configure_team"
        self.projects._check_tool_policy(name)
        cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s",
                       (self.projects.context.tenant_id, receiver))
        row = cursor.fetchone()
        if row is None:
            raise NotFound("receiver", receiver)
        endpoint = row[0]
        args = {"project_id": project, "scope_handle": handle("scope", project, endpoint["scope_id"])}
        bound, root, command = self.projects._authorize(authority, cursor, project, name, args)
        visible = self.projects._visible_scopes(bound, cursor, root)
        if visible is not None and endpoint["scope_id"] not in {*visible, root[0]}:
            raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
        if request.action not in READ_ACTIONS:
            for permission in ("collaborators.manage", "grants.manage"):
                bound._authorize(command, cursor, permission, endpoint["scope_id"])
            if request.action in LIFECYCLE_ACTIONS:
                from runtime.project_http import OAuthScopeDenied

                token = getattr(self.projects, "token_authorization", None)
                if token is not None:
                    try:
                        token.authorize_permissions(("runtime.invoke", "runtime.read", "delivery.manage")
                            if request.action == "rebind_receiver" else ("runtime.invoke",))
                    except OAuthScopeDenied as error:
                        raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref) from error
                bound._authorize(command, cursor, "runtime.invoke", endpoint["scope_id"])
            if request.action == "rebind_receiver":
                for permission in ("delivery.manage", "runtime.read"):
                    bound._authorize(command, cursor, permission, endpoint["scope_id"])
        original = None
        if request.operation_ref is not None:
            self.projects._check_tool_policy("read_message")
            cursor.execute("SELECT m.message_id,m.packet_json->>'target_scope_id',m.packet_json->>'target_agent_slot_id',"
                "m.endpoint_id FROM delivery_messages m JOIN communication_messages c USING(tenant_id,message_id) "
                "WHERE m.tenant_id=%s AND c.project_id=%s AND m.operation_id=%s",
                (self.projects.context.tenant_id, project, request.operation_ref))
            original = cursor.fetchone()
            if original is None:
                raise NotFound("operation", request.operation_ref)
            # Receiver management alone does not grant private delivery history.
            read_bound, _root, _read = self.projects._authorize(authority, cursor, project, "read_message", {"project_id": project})
            self.projects._communication_row(read_bound, cursor, {"project_id": project}, original[0])
            if original[1:3] != (endpoint["scope_id"], endpoint["agent_slot_id"]) or original[3] != receiver:
                raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
        actor = self.projects._communication_address(cursor, project)
        if not lock_endpoint:
            return bound, command, endpoint, actor, original[0] if original else None
        # Follow Domain's Grant -> Scope -> endpoint lock order. The first
        # endpoint read chooses the scope to authorize; freeze and compare that
        # same selection after authorization, before accepting a revision CAS.
        cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND endpoint_id=%s FOR SHARE",
                       (self.projects.context.tenant_id, receiver))
        current = cursor.fetchone()
        if current is None:
            raise NotFound("receiver", receiver)
        current = current[0]
        if (current["revision"] != endpoint["revision"] or
                any(current[key] != endpoint[key] for key in SELECTION_FIELDS)):
            raise RevisionConflict(receiver, endpoint["revision"], current["revision"])
        endpoint = current
        return bound, command, endpoint, actor, original[0] if original else None

    def _row(self, cursor, project, operation, *, lock=False):
        cursor.execute("SELECT payload FROM outbox WHERE tenant_id=%s AND operation_id=%s AND topic=%s" +
                       (" FOR UPDATE" if lock else ""), (self.authority.tenant_id, operation, TOPIC))
        row = cursor.fetchone()
        if row is None or row[0].get("project_id") != project:
            raise NotFound("recovery", operation)
        return row[0]

    def submit(self, project_id, receiver_id, requestdict, client_request_id, credential):
        request = RecoveryRequest.model_validate(requestdict)
        if not isinstance(client_request_id, str) or not 1 <= len(client_request_id) <= 256:
            raise ValueError("a stable client_request_id is required")
        self.projects.service.authenticate(credential)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            bound, command, endpoint, actor, message = self._authorize(cursor, authority, project_id, receiver_id, request,
                lock_endpoint=request.action != "rebind_receiver")
            owner = "recovery-actor:" + digest([bound.context.authority_incarnation, actor])
            hashed = digest([receiver_id, request.model_dump(mode="json")])
            command_id = "receiver-action-" + digest([bound.tenant_id, owner, client_request_id])
            command = command.model_copy(update={"command_id": command_id, "idempotency_key": command_id,
                "correlation_id": command_id, "command_type": "receiver.recovery", "target_kind": "endpoint",
                "target_id": receiver_id, "expected_revision": request.expected_revision})
            bound._lock_command_identity(cursor, command)
            cursor.execute("SELECT input_digest,result_json FROM collaboration_commands WHERE tenant_id=%s AND project_id=%s "
                "AND principal_ref=%s AND client_request_id=%s FOR UPDATE", (bound.tenant_id, project_id, owner, client_request_id))
            prior = cursor.fetchone()
            if prior is not None:
                if prior[0] != hashed:
                    raise IdempotencyConflict(client_request_id)
                return self._row(cursor, project_id, prior[1]["operation_id"])["operation"]
            if endpoint["revision"] != request.expected_revision:
                raise RevisionConflict(receiver_id, request.expected_revision, endpoint["revision"])
            if endpoint["status"] != "active":
                raise ValueError("receiver is not active")
            selected = None
            if request.action == "rebind_receiver":
                from runtime.receiver_rebind import capture_rebind_selection

                selected = capture_rebind_selection(self, cursor, authority, project_id, endpoint, request)
                command = command.model_copy(update={"payload": {**command.payload, "receiver_rebind": selected}})
            now = bound.canonical_now(cursor).isoformat()
            operation = {"operation_id": "receiver-recovery-" + uuid.uuid4().hex, "kind": "recovery", "state": "queued",
                "message_handle": handle("message", project_id, message) if message else None, "receiver_ref": receiver_id,
                "binding_epoch": endpoint["revision"], "effect_state": "committed", "reason_code": None,
                "evidence_refs": ["command:" + command_id], "revision": 1, "created_at": now, "updated_at": now}
            context = asdict(self.projects.context)
            context.pop("credential_hash", None)
            payload = {"schema_version": "acs-receiver-recovery/1", "project_id": project_id, "receiver_id": receiver_id,
                "actor": actor, "issuer_context": context, "profile": self.projects.profile,
                "request": request.model_dump(mode="json"), "command": command.model_dump(mode="json"), "operation": operation}
            if selected is not None:
                payload["rebind_selection"] = selected
            cursor.execute("INSERT INTO operations(operation_id,tenant_id,command_id,provider,provider_workflow_id,status) "
                "VALUES (%s,%s,%s,'communication-recovery',%s,'committed')",
                (operation["operation_id"], bound.tenant_id, command_id, operation["operation_id"]))
            bound._outbox(cursor, command, operation["operation_id"], TOPIC, payload)
            cursor.execute("INSERT INTO collaboration_commands(tenant_id,project_id,principal_ref,client_request_id,tool_name,"
                "input_digest,command_id,result_json) VALUES (%s,%s,%s,%s,'receiver.recovery',%s,%s,%s)",
                (bound.tenant_id, project_id, owner, client_request_id, hashed, command_id, json.dumps(operation)))
            cursor.execute("INSERT INTO domain_events(tenant_id,target_kind,target_id,to_state,initiated_by,lineage_mode,command_id,"
                "resulting_revision,evidence_refs,command_hash_version,canonical_hash) VALUES (%s,'endpoint',%s,'receiver.recovery.queued',"
                "%s,'external_command',%s,1,'[]','v2',%s)", (bound.tenant_id, receiver_id, bound.context.principal_ref, command_id, hashed))
            self._authorize(cursor, authority, project_id, receiver_id, request)
            return operation

    def read(self, project_id, operation_ref, credential):
        self.projects.service.authenticate(credential)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self._row(cursor, project_id, operation_ref)
            request = RecoveryRequest.model_validate(payload["request"])
            _bound, _cmd, _endpoint, actor, _message = self._authorize(cursor, authority, project_id, payload["receiver_id"], request)
            if actor != payload["actor"]:
                raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
            return payload["operation"]

    def _save(self, cursor, payload, operation, *, done=False):
        payload = payload | {"operation": operation}
        cursor.execute("UPDATE outbox SET payload=%s,delivered_at=CASE WHEN %s THEN COALESCE(delivered_at,clock_timestamp()) "
            "ELSE delivered_at END WHERE tenant_id=%s AND operation_id=%s AND topic=%s",
            (json.dumps(payload), done, self.authority.tenant_id, operation["operation_id"], TOPIC))
        cursor.execute("UPDATE operations SET updated_at=clock_timestamp() WHERE tenant_id=%s AND operation_id=%s",
                       (self.authority.tenant_id, operation["operation_id"]))

    def _original_authority(self, cursor, payload, request, *, lock_endpoint=True):
        from runtime.project_service import ProjectService
        from runtime.surfaces import SharedService

        original = copy(self.authority)
        original.context = AuthenticatedContext(**payload["issuer_context"])
        projects = ProjectService(SharedService(original, LocalCredentialAuthenticator(original.context)),
                                  self.projects.catalog, profile=payload["profile"])
        checker = ReceiverRecoveryOperations(projects)
        options = {} if lock_endpoint else {"lock_endpoint": False}
        bound, observation, endpoint, actor, _message = checker._authorize(
            cursor, original, payload["project_id"], payload["receiver_id"], request, **options)
        if actor != payload["actor"]:
            raise AuthorizationDenied(original.context.principal_ref, original.context.grant_ref)
        stored = CommandEnvelope.model_validate_json(json.dumps(payload["command"]), strict=True)
        # The accepted operation survives the original request's automatic
        # 30-second admission budget. Recheck its immutable issuer/Grant using
        # a fresh bounded observation, without replacing the stored command.
        command = stored.model_copy(update={"issued_at": observation.issued_at, "deadline": observation.deadline})
        bound._authorize(command, cursor, "profile." + payload["profile"])
        return OriginalRecoveryAuthority(bound, stored, command, endpoint, actor)

    @staticmethod
    def _matches_provider(provider, endpoint):
        describe = getattr(provider, "descriptor", None)
        if not callable(describe):
            return False
        description = describe()
        return (isinstance(description, dict) and endpoint["status"] == "active"
                and all(description.get(key) == endpoint[key] for key in SELECTION_FIELDS))

    def _fenced_lifecycle(self, project_id, operation_ref, credential):
        # Runtime-installed objects only; no public request can install or name
        # another backend. Unconfigured legacy providers keep the unsupported
        # lifecycle result until an actual fenced transport is installed.
        transports = getattr(self.authority, "_receiver_lifecycle_transports", None)
        if not transports:
            return None
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self._row(cursor, project_id, operation_ref, lock=True)
            request = RecoveryRequest.model_validate(payload["request"])
            if request.action not in LIFECYCLE_ACTIONS:
                return None
            if request.action == "rebind_receiver" and not isinstance(payload.get("rebind_selection"), dict):
                return None  # Retained legacy commands have no sealed target authority.
            _bound, _cmd, _endpoint, actor, _message = self._authorize(
                cursor, authority, project_id, payload["receiver_id"], request, lock_endpoint=False)
            if actor != payload["actor"]:
                raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
            from runtime.receiver_rebind import lifecycle_receiver

            transport = transports.get(lifecycle_receiver(payload)[0])
            if transport is None:
                return None
        from runtime.receiver_lifecycle_executor import ReceiverLifecycleExecutor

        return ReceiverLifecycleExecutor(self, transport).advance(project_id, operation_ref, credential)

    def advance(self, project_id, operation_ref, credential):
        self.projects.service.authenticate(credential)
        fenced = self._fenced_lifecycle(project_id, operation_ref, credential)
        if fenced is not None:
            return fenced
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self._row(cursor, project_id, operation_ref, lock=True)
            request = RecoveryRequest.model_validate(payload["request"])
            bound, _cmd, endpoint, actor, _message = self._authorize(cursor, authority, project_id, payload["receiver_id"], request)
            if actor != payload["actor"]:
                raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
            operation = payload["operation"]
            if operation["state"] in FINAL:
                return operation
            if operation["state"] != "queued":
                # Another executor may still be active. Observe the durable
                # marker consistently; never invent a terminal result or replay.
                return operation
            self._original_authority(cursor, payload, request)
            if endpoint["revision"] != request.expected_revision:
                operation = operation | {"state": "superseded", "reason_code": "receiver_binding_changed",
                    "updated_at": bound.canonical_now(cursor).isoformat(), "revision": operation["revision"] + 1}
                self._save(cursor, payload, operation, done=True)
                return operation
            if request.action in LIFECYCLE_ACTIONS:
                # Existing prepare_runtime() callbacks have no signed command,
                # expected binding or authorization check at their own effect
                # boundary. Presence/readback cannot establish that contract.
                # No fenced transport was installed for this selected receiver.
                operation = operation | {"state": "definitively_rejected", "effect_state": "committed",
                    "reason_code": request.action + "_fenced_lifecycle_unsupported",
                    "updated_at": bound.canonical_now(cursor).isoformat(), "revision": operation["revision"] + 1}
                self._save(cursor, payload, operation, done=True)
                return operation
            operation = operation | {"state": "preparing" if request.action in READ_ACTIONS else "submitting",
                "effect_state": "committed" if request.action in READ_ACTIONS else "native_possible",
                "revision": operation["revision"] + 1, "updated_at": bound.canonical_now(cursor).isoformat()}
            self._save(cursor, payload, operation)
        # The committed marker precedes every external call, and no DB write
        # transaction remains open while a receiver or Native API is contacted.
        state, reason, evidence, effect = "completed", None, [], "committed"
        try:
            self.projects.service.authenticate(credential)
            provider = self.authority._delivery_endpoints.get(payload["receiver_id"])
            if request.action == "inspect":
                if not self._matches_provider(provider, endpoint):
                    state, reason = "unknown", "receiver_binding_unconfirmed"
                else:
                    observe = getattr(provider, "inspect_runtime", None)
                    result = observe() if callable(observe) else {"state": "unknown"}
                    if not self._matches_provider(provider, endpoint):
                        state, reason = "unknown", "receiver_binding_changed_during_observation"
                    else:
                        observed = result.get("state", "unknown")
                        reason = "receiver_" + (observed if observed in {"idle", "busy", "online", "offline", "unknown"} else "unknown")
            elif request.action == "reconcile":
                result = CommunicationDeliveryObserver(self.projects).observe(project_id, request.operation_ref, credential,
                    reconcile=True, expected_revision=request.expected_revision)
                reason = "delivery_" + result["delivery_state"]
            elif request.action == "retry_delivery":
                observer = CommunicationDeliveryObserver(self.projects)
                result = observer.observe(project_id, request.operation_ref, credential, expected_revision=request.expected_revision)
                if result["delivery_state"] == "uncertain":
                    state, reason = "definitively_rejected", "native_outcome_unknown_no_retry"
                elif result["delivery_state"] not in {"queued", "retry_wait", "delivering"}:
                    reason = "delivery_" + result["delivery_state"]
                else:
                    identity = {"tenant_id": self.authority.tenant_id, "message_id": result["message_handle"].rsplit(":", 1)[1],
                                "operation_id": request.operation_ref}
                    effect = "native_possible"
                    dispatched = DeliveryDispatcher(DeliveryService(self.authority, self.authority._delivery_endpoints)).dispatch(identity)
                    reason = "delivery_" + dispatched["status"]
                    state = "unknown" if dispatched["status"] == "uncertain" else "completed"
        except Exception:  # noqa: BLE001 - an external call may already have a Native effect.
            state, reason = "unknown", "recovery_observation_unavailable"
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            current = self._row(cursor, project_id, operation_ref, lock=True)
            # Authorization loss after the call cannot erase the durable marker
            # or disclose a private result. An active executor may finish later.
            self.projects.service.authenticate(credential)
            bound, _cmd, after, actor, _msg = self._authorize(cursor, authority, project_id, payload["receiver_id"], request)
            if actor != payload["actor"]:
                raise AuthorizationDenied(self.projects.context.principal_ref, self.projects.context.grant_ref)
            self._original_authority(cursor, payload, request)
            if after["revision"] != request.expected_revision:
                state, reason = "superseded", "receiver_binding_changed_during_recovery"
            final = current["operation"] | {"state": state, "reason_code": reason, "effect_state": effect,
                "evidence_refs": operation["evidence_refs"] + evidence,
                "revision": current["operation"]["revision"] + 1, "updated_at": bound.canonical_now(cursor).isoformat()}
            self._save(cursor, current, final, done=True)
            return final
