"""PostgreSQL authority for explicit, versioned native Harness session bindings.

The binding receipt is external evidence. This module does not spawn a Harness,
verify its installed version, or make an Agent decision.
"""
from __future__ import annotations

import json
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime.errors import AuthorizationDenied, InvalidTransition, NotFound, RevisionConflict
from runtime.models import CommandEnvelope, CommandResult


class BindingChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: str = Field(min_length=1, max_length=256)
    scope_id: str = Field(min_length=1, max_length=256)
    agent_slot_id: str = Field(min_length=1, max_length=256)
    driver_kind: Literal["codex", "opencode"]
    native_session_ref: str = Field(min_length=1, max_length=512)
    installed_version: str = Field(min_length=1, max_length=128)
    receipt_ref: str = Field(min_length=1, max_length=512)

    @field_validator("binding_id", "scope_id", "agent_slot_id", "native_session_ref", "installed_version", "receipt_ref")
    @classmethod
    def visible_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("binding field must be visible text")
        return value


class BindingRetire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    binding_id: str = Field(min_length=1, max_length=256)


class BindingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    result_id: str = Field(min_length=1, max_length=256)
    binding_id: str = Field(min_length=1, max_length=256)
    native_session_ref: str = Field(min_length=1, max_length=512)
    result_ref: str = Field(min_length=1, max_length=512)


class HarnessSessionAuthority:
    PERMISSIONS: ClassVar[dict[str, str]] = {
        "harness_session.attach": "harness_session.manage",
        "harness_session.replace": "harness_session.manage",
        "harness_session.retire": "harness_session.manage",
        "harness_session.result": "harness_session.result",
        "harness_session.read": "harness_session.read",
    }

    def __init__(self, authority):
        self.authority = authority

    def _head(self, cursor, command, permission):
        cursor.execute(
            "SELECT scope_id,agent_slot_id FROM work_items "
            "WHERE tenant_id=%s AND work_item_id=%s",
            (command.tenant_id, command.target_id),
        )
        observed = cursor.fetchone()
        if observed is None:
            raise NotFound("work_item", command.target_id)
        # Delivery takes the Grant/Scope lock before its WorkItem lock. Keep
        # that order and recheck the unlocked lookup after the WorkItem locks.
        self.authority._authorize(command, cursor, permission, observed[0])
        cursor.execute(
            "SELECT scope_id,agent_slot_id,execution_status FROM work_items "
            "WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
            (command.tenant_id, command.target_id),
        )
        row = cursor.fetchone()
        if row is None or row[:2] != observed:
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute(
            "SELECT a.tenant_id,a.scope_id,a.status,s.tenant_id,s.status "
            "FROM agent_slots a JOIN scopes s ON s.scope_id=a.scope_id "
            "WHERE a.agent_slot_id=%s FOR UPDATE OF a,s",
            (row[1],),
        )
        slot = cursor.fetchone()
        if (slot is None or (slot[0], slot[1], slot[3], slot[4]) !=
                (command.tenant_id, row[0], command.tenant_id, "active")):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        cursor.execute(
            "SELECT revision,active_binding_id,scope_id,agent_slot_id "
            "FROM harness_session_heads WHERE tenant_id=%s AND work_item_id=%s FOR UPDATE",
            (command.tenant_id, command.target_id),
        )
        head = cursor.fetchone()
        if head is not None and (head[2], head[3]) != (row[0], row[1]):
            raise AuthorizationDenied(command.principal_ref, command.grant_ref)
        return row[0], row[1], row[2], slot[2], head

    def change(self, command: CommandEnvelope, request: BindingChange | BindingRetire) -> CommandResult:
        name = command.command_type
        if name not in {"harness_session.attach", "harness_session.replace", "harness_session.retire"} or command.target_kind != "work_item":
            raise ValueError("unsupported Harness binding command")
        model = BindingRetire if name == "harness_session.retire" else BindingChange
        request = model.model_validate_json(request.model_dump_json(), strict=True)
        a = self.authority
        result = CommandResult(command_id=command.command_id, operation_id="harness:" + command.command_id,
                               target_id=command.target_id, revision=command.expected_revision + 1,
                               state="retired" if name.endswith("retire") else "active")
        extra = {"harness_session": request.model_dump(mode="json")}
        with a._connect() as connection, connection.cursor() as cursor:
            scope_id, agent_slot_id, work_status, slot_status, head = self._head(
                cursor, command, self.PERMISSIONS[name])
            replay, digest = a._dedup(cursor, command, result, extra)
            if replay is not None:
                return replay
            if name != "harness_session.retire" and work_status in ("failed", "cancelled"):
                raise InvalidTransition(work_status, name)
            if name != "harness_session.retire" and slot_status != "active":
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            current_revision = int(head[0]) if head else 0
            active_id = head[1] if head else None
            if current_revision != command.expected_revision:
                raise RevisionConflict(command.target_id, command.expected_revision, current_revision)
            if name == "harness_session.attach" and active_id is not None:
                raise InvalidTransition("active", "attach")
            if name in {"harness_session.replace", "harness_session.retire"} and active_id is None:
                raise InvalidTransition("unbound", name)
            if name == "harness_session.retire" and request.binding_id != active_id:
                raise RevisionConflict(request.binding_id, command.expected_revision, current_revision)
            if name != "harness_session.retire" and (request.scope_id, request.agent_slot_id) != (scope_id, agent_slot_id):
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            if name == "harness_session.replace" and request.binding_id == active_id:
                raise InvalidTransition("active", "replace_same_binding")
            if head is None:
                cursor.execute(
                    "INSERT INTO harness_session_heads(tenant_id,work_item_id,scope_id,agent_slot_id,revision) "
                    "VALUES (%s,%s,%s,%s,0)",
                    (command.tenant_id, command.target_id, scope_id, agent_slot_id),
                )
            if active_id is not None:
                cursor.execute(
                    "UPDATE harness_session_bindings SET status='retired',retired_by=%s,"
                    "retired_command_id=%s,retired_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND binding_id=%s AND work_item_id=%s AND status='active'",
                    (command.principal_ref, command.command_id, command.tenant_id, active_id, command.target_id),
                )
                if cursor.rowcount != 1:
                    raise InvalidTransition("binding_changed", name)
            new_id = None if name == "harness_session.retire" else request.binding_id
            if new_id is not None:
                cursor.execute(
                    "INSERT INTO harness_session_bindings(tenant_id,binding_id,work_item_id,scope_id,agent_slot_id,"
                    "revision,driver_kind,native_session_ref,installed_version,receipt_ref,status,attached_by,attached_command_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)",
                    (command.tenant_id, new_id, command.target_id, scope_id, agent_slot_id,
                     result.revision, request.driver_kind, request.native_session_ref,
                     request.installed_version, request.receipt_ref, command.principal_ref, command.command_id),
                )
            cursor.execute(
                "UPDATE harness_session_heads SET revision=%s,active_binding_id=%s,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND work_item_id=%s",
                (result.revision, new_id, command.tenant_id, command.target_id),
            )
            self._record(cursor, command, result, digest, name, {"binding_id": new_id or active_id,
                          "scope_id": scope_id, "agent_slot_id": agent_slot_id})
        return result

    def admit_result(self, command: CommandEnvelope, request: BindingResult) -> CommandResult:
        if command.command_type != "harness_session.result" or command.target_kind != "work_item":
            raise ValueError("unsupported Harness result command")
        request = BindingResult.model_validate_json(request.model_dump_json(), strict=True)
        a = self.authority
        result = CommandResult(command_id=command.command_id, operation_id="harness:" + command.command_id,
                               target_id=command.target_id, revision=command.expected_revision, state="pending")
        with a._connect() as connection, connection.cursor() as cursor:
            scope_id, _, work_status, slot_status, head = self._head(
                cursor, command, self.PERMISSIONS[command.command_type])
            replay, digest = a._dedup(cursor, command, result, {"harness_session_result": request.model_dump(mode="json")})
            if replay is not None:
                return replay
            revision = int(head[0]) if head else 0
            if command.expected_revision != revision:
                raise RevisionConflict(command.target_id, command.expected_revision, revision)
            cursor.execute(
                "SELECT work_item_id,scope_id,native_session_ref,status FROM harness_session_bindings "
                "WHERE tenant_id=%s AND binding_id=%s FOR UPDATE",
                (command.tenant_id, request.binding_id),
            )
            binding = cursor.fetchone()
            if binding is None or binding[0:2] != (command.target_id, scope_id) or binding[2] != request.native_session_ref:
                raise AuthorizationDenied(command.principal_ref, command.grant_ref)
            disposition = ("current" if head and head[1] == request.binding_id
                           and binding[3] == "active" and slot_status == "active"
                           and work_status not in ("failed", "cancelled")
                           else "fenced_late")
            result = result.model_copy(update={"state": disposition})
            cursor.execute(
                "INSERT INTO harness_session_result_admissions(tenant_id,result_id,work_item_id,binding_id,"
                "native_session_ref,result_ref,disposition,command_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (command.tenant_id, request.result_id, command.target_id, request.binding_id,
                 request.native_session_ref, request.result_ref, disposition, command.command_id),
            )
            cursor.execute(
                "UPDATE command_dedup SET result_json=%s WHERE tenant_id=%s AND command_id=%s",
                (result.model_dump_json(), command.tenant_id, command.command_id),
            )
            self._record(cursor, command, result, digest, command.command_type,
                         {"binding_id": request.binding_id, "result_id": request.result_id,
                          "disposition": disposition})
        return result

    def read(self, command: CommandEnvelope) -> dict:
        if command.command_type != "harness_session.read" or command.target_kind != "work_item":
            raise ValueError("unsupported Harness binding read")
        with self.authority._connect() as connection, connection.cursor() as cursor:
            scope_id, agent_slot_id, _, _, head = self._head(
                cursor, command, self.PERMISSIONS[command.command_type])
            revision = int(head[0]) if head else 0
            if command.expected_revision != revision:
                raise RevisionConflict(command.target_id, command.expected_revision, revision)
            cursor.execute(
                "SELECT binding_id,revision,driver_kind,native_session_ref,installed_version,receipt_ref,"
                "status,attached_by,attached_command_id,retired_by,retired_command_id "
                "FROM harness_session_bindings WHERE tenant_id=%s AND work_item_id=%s ORDER BY revision",
                (command.tenant_id, command.target_id),
            )
            keys = ("binding_id", "revision", "driver_kind", "native_session_ref", "installed_version",
                    "receipt_ref", "status", "attached_by", "attached_command_id", "retired_by", "retired_command_id")
            bindings = [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]
            return {"tenant_id": command.tenant_id, "work_item_id": command.target_id,
                    "scope_id": scope_id, "agent_slot_id": agent_slot_id, "revision": revision,
                    "active_binding_id": head[1] if head else None, "bindings": bindings}

    def _record(self, cursor, command, result, digest, name, payload):
        self.authority._operation(cursor, command, result.operation_id)
        cursor.execute(
            "INSERT INTO domain_events(tenant_id,work_item_id,target_kind,target_id,related_work_item_id,"
            "to_state,initiated_by,lineage_mode,command_id,resulting_revision,evidence_refs,"
            "command_hash_version,canonical_hash) "
            "VALUES (%s,NULL,'harness_session',%s,%s,%s,%s,'external_command',%s,%s,%s,'v2',%s)",
            (command.tenant_id, command.target_id, command.target_id, result.state,
             command.principal_ref, command.command_id, result.revision,
             json.dumps([payload]), digest),
        )
        self.authority._outbox(cursor, command, result.operation_id, name, payload)
