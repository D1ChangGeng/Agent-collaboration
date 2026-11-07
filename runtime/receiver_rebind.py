"""Ready-target rebind on the accepted recovery Outbox, without Native replay.

Selection is frozen at submission. Publication changes only receiving selection
and epochs; original Messages, attempts, permits and unknown results stay put.
"""
from __future__ import annotations

from copy import deepcopy

from runtime.errors import AcceptanceGuardFailed, AuthorizationDenied, RevisionConflict
from runtime.project_common import canonical, digest

FIELDS = ("scope_id", "agent_slot_id", "machine_id", "node_id", "boot_incarnation", "revision")


def lifecycle_receiver(payload):
    if payload.get("request", {}).get("action") == "rebind_receiver":
        selected = payload["rebind_selection"]
        return selected["target_endpoint_id"], selected["target"]["revision"]
    return payload["receiver_id"], payload["operation"]["binding_epoch"]


def capture_rebind_selection(recovery, cursor, authority, project, source, request):
    """Current explicit management authority over both registered endpoints."""
    target_id = request.target_endpoint_ref
    if target_id == source["endpoint_id"]:
        raise ValueError("rebind requires a different receiving endpoint")
    target_request = request.model_copy(update={"action": "prepare_receiver", "operation_ref": None})
    bound, command, target, _actor, _message = recovery._authorize(
        cursor, authority, project, target_id, target_request, lock_endpoint=False)
    if (source["scope_id"], source["agent_slot_id"]) != (target["scope_id"], target["agent_slot_id"]):
        raise AuthorizationDenied(bound.context.principal_ref, bound.context.grant_ref)
    for permission in ("delivery.manage", "runtime.read"):
        bound._authorize(command, cursor, permission, target["scope_id"])
    # bind_endpoint/configure_team take this Slot before changing its receiving
    # set. Row locks on the endpoints alone cannot fence a concurrent INSERT.
    cursor.execute("SELECT scope_id,status FROM agent_slots WHERE tenant_id=%s AND agent_slot_id=%s FOR SHARE NOWAIT",
        (bound.tenant_id, source["agent_slot_id"]))
    if cursor.fetchone() != (source["scope_id"], "active"):
        raise AcceptanceGuardFailed("rebind stable Slot is unavailable")
    cursor.execute("SELECT revision,definition FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s "
        "AND scope_id=%s FOR SHARE NOWAIT", (bound.tenant_id, project, source["scope_id"]))
    team = cursor.fetchone()
    member = next((item for item in team[1]["members"] if item["agent_slot_id"] == source["agent_slot_id"]), {}) if team else {}
    if member.get("endpoint_id") not in {None, source["endpoint_id"]}:
        raise AcceptanceGuardFailed("current receiving preference differs from the requested source")
    cursor.execute("SELECT to_jsonb(e) FROM delivery_endpoints e WHERE tenant_id=%s AND scope_id=%s "
        "AND agent_slot_id=%s AND status='active' ORDER BY endpoint_id FOR SHARE NOWAIT",
        (bound.tenant_id, source["scope_id"], source["agent_slot_id"]))
    endpoints = {row[0]["endpoint_id"]: row[0] for row in cursor.fetchall()}
    for expected in (source, target):
        current = endpoints.get(expected["endpoint_id"])
        if current is None or any(current.get(key) != expected.get(key) for key in FIELDS):
            raise AcceptanceGuardFailed("rebind selection changed or is inactive")
    # Without a configured member there is no preference to publish. Retiring
    # the explicit source must leave precisely the explicit target, not a guess.
    if not member and set(endpoints) != {source["endpoint_id"], target_id}:
        raise AcceptanceGuardFailed("rebind receiving selection is ambiguous")
    return {"source": {key: source[key] for key in FIELDS},
        "target_endpoint_id": target_id, "target": {key: target[key] for key in FIELDS},
        "team_revision": team[0] if team else None, "team_digest": digest(team[1]) if team else None,
        "has_member": bool(member)}


def require_rebind_selection(recovery, cursor, payload, checked):
    from runtime.receiver_recovery_operations import ReceiverRecoveryOperations, RecoveryRequest

    selected = payload.get("rebind_selection")
    if not isinstance(selected, dict) or checked.stored_command.payload.get("receiver_rebind") != selected:
        raise AcceptanceGuardFailed("original rebind selection is unavailable")
    current = capture_rebind_selection(ReceiverRecoveryOperations(_original_projects(recovery, payload, checked)),
        cursor, checked.authority, payload["project_id"], checked.endpoint, RecoveryRequest.model_validate(payload["request"]))
    if current != selected:
        raise AcceptanceGuardFailed("accepted rebind selection changed")
    if checked.endpoint["revision"] != payload["request"]["expected_revision"]:
        raise RevisionConflict(payload["receiver_id"], payload["request"]["expected_revision"], checked.endpoint["revision"])
    return selected


def _original_projects(recovery, payload, checked):
    from runtime.auth import LocalCredentialAuthenticator
    from runtime.project_service import ProjectService
    from runtime.surfaces import SharedService

    return ProjectService(SharedService(checked.authority, LocalCredentialAuthenticator(checked.authority.context)),
        recovery.projects.catalog, profile=payload["profile"])


def publish_rebind(recovery, cursor, project, operation_ref, *, journal_generation):
    """Atomic config CAS after a verified ready observation, with no Host I/O."""
    from runtime.receiver_lifecycle_contract import (
        LifecycleSource,
        LifecycleTarget,
        SignedCapacityObservation,
        SignedLifecycleChallenge,
        verify_observation,
    )
    from runtime.receiver_lifecycle_domain import checked_lifecycle_authority
    from runtime.receiver_lifecycle_issuance import (
        LifecycleIssuanceRejected,
        _authorizer,
        _clock,
        _derive,
        _state,
        _typed,
    )

    payload = recovery._row(cursor, project, operation_ref, lock=True)
    data = _state(payload)
    if (payload["request"]["action"] != "rebind_receiver" or data is None
            or data["phase"] != "rebind_ready" or data.get("permit") is not None):
        raise LifecycleIssuanceRejected("rebind_ready_target_required")
    checked, source, snapshot = checked_lifecycle_authority(recovery, cursor, payload,
        journal_generation=journal_generation,
        expected_source=_typed(LifecycleSource, data["source"]), expected_target=_typed(LifecycleTarget, data["target"]))
    current = _authorizer(recovery, cursor, project, operation_ref, journal_generation, data)
    observed = verify_observation(_typed(SignedCapacityObservation, data["observation"]),
        challenge=_typed(SignedLifecycleChallenge, data["challenge"]).challenge, expected_source=source,
        actual_target=snapshot.target(), node_public_key=snapshot.binding.node_public_key,
        clock=_clock(checked, cursor, source, snapshot.target()), authorize_current=current)
    if _derive("rebind_receiver", observed.capacity) != (None, "lifecycle_rebind_ready"):
        raise LifecycleIssuanceRejected("rebind_ready_target_required")
    selected = require_rebind_selection(recovery, cursor, payload, checked)
    scope, slot = selected["source"]["scope_id"], selected["source"]["agent_slot_id"]
    definition = None
    if selected["has_member"]:
        cursor.execute("SELECT definition FROM collaboration_teams WHERE tenant_id=%s AND project_id=%s "
            "AND scope_id=%s FOR UPDATE NOWAIT", (checked.authority.tenant_id, project, scope))
        definition = deepcopy(cursor.fetchone()[0])
        for member in definition["members"]:
            if member["agent_slot_id"] == slot:
                member["endpoint_id"] = selected["target_endpoint_id"]
    # Upgrade locks in the same deterministic order as the selection read.
    cursor.execute("SELECT endpoint_id FROM delivery_endpoints WHERE tenant_id=%s AND endpoint_id=ANY(%s::text[]) "
        "ORDER BY endpoint_id FOR UPDATE NOWAIT", (checked.authority.tenant_id,
            [payload["receiver_id"], selected["target_endpoint_id"]]))
    cursor.fetchall()
    # No writes precede the final current-authority and observation time fence.
    verify_observation(_typed(SignedCapacityObservation, data["observation"]),
        challenge=_typed(SignedLifecycleChallenge, data["challenge"]).challenge, expected_source=source,
        actual_target=snapshot.target(), node_public_key=snapshot.binding.node_public_key,
        clock=_clock(checked, cursor, source, snapshot.target()), authorize_current=current)
    if definition is not None:
        cursor.execute("UPDATE collaboration_teams SET definition=%s,revision=revision+1 WHERE tenant_id=%s "
            "AND project_id=%s AND scope_id=%s", (canonical(definition), checked.authority.tenant_id, project, scope))
    epoch = max(selected["source"]["revision"], selected["target"]["revision"]) + 1
    cursor.execute("UPDATE delivery_endpoints SET status='retired',revision=revision+1,command_id=%s,operation_id=%s "
        "WHERE tenant_id=%s AND endpoint_id=%s", (source.command_id, operation_ref, source.tenant_id, payload["receiver_id"]))
    cursor.execute("UPDATE delivery_endpoints SET revision=%s,command_id=%s,operation_id=%s WHERE tenant_id=%s "
        "AND endpoint_id=%s", (epoch, source.command_id, operation_ref, source.tenant_id, selected["target_endpoint_id"]))
    evidence = "receiver-rebind:" + digest([operation_ref, selected, epoch, observed.model_dump(mode="json")])
    data.update(phase="settled", rebind_result={"endpoint_id": selected["target_endpoint_id"], "binding_epoch": epoch,
        "native_session_ref": observed.capacity.native_session_ref, "provider_generation": observed.capacity.provider_generation})
    old = payload["operation"]
    operation = old | {"state": "completed", "reason_code": "receiver_rebound", "revision": old["revision"] + 1,
        "updated_at": checked.authority.canonical_now(cursor).isoformat(), "evidence_refs": [*old["evidence_refs"], evidence]}
    cursor.execute("INSERT INTO domain_events(tenant_id,target_kind,target_id,to_state,initiated_by,lineage_mode,command_id,"
        "resulting_revision,evidence_refs,command_hash_version,canonical_hash) VALUES (%s,'endpoint',%s,'receiver.rebound',"
        "%s,'external_command',%s,%s,%s,'v2',%s)", (source.tenant_id, selected["target_endpoint_id"], source.principal_ref,
            source.command_id, epoch, canonical([evidence]), digest(selected)))
    recovery._save(cursor, payload | {"lifecycle": data}, operation, done=True)
    return operation
