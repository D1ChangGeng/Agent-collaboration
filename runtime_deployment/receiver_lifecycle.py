"""Opt-in control-plane construction for the concrete native Receiver factories.

Provisioning is explicit, capacity-local and happens before Driver claims or any
Native process. Normal control-plane startup verifies an already adopted journal.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from runtime.auth import LocalCredentialAuthenticator
from runtime.codex_driver import DriverJournal, DriverRejected
from runtime.project_service import ProjectService
from runtime.receiver_crypto import load_owner_signing_key, sha256, verify
from runtime.receiver_lifecycle_capacity import (
    CapacityEvidenceUnavailable,
    capture_capacity_profile,
    create_capacity_reservation,
    recover_capacity_profile,
)
from runtime.receiver_lifecycle_contract import LifecyclePlan, SignedLifecyclePermit
from runtime.receiver_lifecycle_core import LifecycleCoreCallbacks
from runtime.receiver_lifecycle_node import ReceiverLifecycleNode
from runtime.receiver_paths import private_parent
from runtime.surface_config import PrivateReference
from runtime.surfaces import SharedService

LIFECYCLE_OPTIONAL = {"lifecycle_control", "lifecycle_initialize_journal", "lifecycle_catalog",
                      "lifecycle_catalog_sha256", "lifecycle_account_ref", "lifecycle_fresh_capacity_seconds",
                      "lifecycle_message_wake"}


def validate_lifecycle_settings(settings):
    for key in ("lifecycle_control", "lifecycle_initialize_journal", "lifecycle_message_wake"):
        if type(settings.get(key, False)) is not bool:
            raise ValueError("lifecycle factory switches must be explicit booleans")
    if not settings.get("lifecycle_control", False):
        if settings.get("lifecycle_initialize_journal", False) or settings.get("lifecycle_message_wake", False) or any(
                key in settings for key in ("lifecycle_catalog", "lifecycle_catalog_sha256", "lifecycle_account_ref",
                                            "lifecycle_fresh_capacity_seconds")):
            raise ValueError("lifecycle setup requires explicit control-plane mode")
        return
    catalog = settings.get("lifecycle_catalog")
    if (type(catalog) is not str or not Path(catalog).is_absolute()
            or type(settings.get("lifecycle_catalog_sha256")) is not str
            or len(settings["lifecycle_catalog_sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in settings["lifecycle_catalog_sha256"])):
        raise ValueError("lifecycle requires an actual pinned ProjectService catalog")
    PrivateReference.model_validate(settings.get("lifecycle_account_ref"), strict=True)
    seconds = settings.get("lifecycle_fresh_capacity_seconds", 15)
    if type(seconds) is not int or not 1 <= seconds <= 30:
        raise ValueError("fresh lifecycle capacity window must be an integer within 30 seconds")


def _namespace_authority(capacity, namespace, binding_id, binding, *, for_provision=False):
    settings, registration = capacity.settings, capacity.config.binding.registration
    if (Path(namespace) != Path(settings["driver_journal"]).parent
            or Path(settings["driver_journal"]).name != "driver.sqlite"
            or binding_id != settings["binding_id"] or binding != capacity.binding):
        raise PermissionError("configured lifecycle capacity namespace differs")
    namespace = Path(namespace)
    # Before atomic mkdir, authorize the actual private parent. A missing
    # namespace cannot itself be opened as proof of a private directory.
    checked = namespace.parent if for_provision and not namespace.exists() else namespace
    descriptor, _identity = private_parent(checked)
    if descriptor >= 0:  # Windows validation uses no POSIX directory descriptor.
        os.close(descriptor)
    with capacity.authority._connect() as connection, connection.cursor() as cursor:
        runtime, node, bound, key, _expiry = capacity.authority.enrollment.current_runtime_snapshot(cursor, registration.runtime_id)
        if ((runtime["revision"], bound["binding_revision"], bound["boot_incarnation"], node["scope_id"], node["agent_slot_id"], key["key_id"]) !=
                (registration.runtime_revision, registration.node_binding_revision, registration.boot_incarnation,
                 registration.scope_id, registration.agent_slot_id, capacity.config.binding.node_key_id)):
            raise PermissionError("current enrolled lifecycle namespace differs")
        if _expiry is not None and capacity.authority.canonical_now(cursor) >= _expiry:
            raise PermissionError("current enrolled lifecycle namespace expired")
        if for_provision:
            # A missing whole directory is not proof that this enrolled capacity
            # was never used. Core's retained original lifecycle plans survive
            # Node storage loss and prevent recreating their Native namespace.
            cursor.execute("SELECT 1 FROM (SELECT CASE WHEN topic='message.delivery' THEN payload->'receiver_wake'->'lifecycle' "
                "ELSE payload->'lifecycle' END lifecycle FROM outbox WHERE tenant_id=%s "
                "AND topic IN ('communication.receiver.recovery','message.delivery')) history "
                "WHERE lifecycle->'target'->'registration'->>'registration_id'=%s AND "
                "COALESCE(lifecycle->'plan'->'capacity'->>'driver_binding_id',lifecycle->>'driver_binding_id',"
                "lifecycle->'observation'->'observation'->'capacity'->>'driver_binding_id')=%s AND "
                "(lifecycle->>'first_plan_digest' IS NOT NULL OR lifecycle->>'original_capacity_digest' IS NOT NULL OR "
                "lifecycle->'observation'->'observation'->'capacity'->>'state' IN ('existing','stopped')) LIMIT 1",
                (capacity.authority.tenant_id, registration.registration_id, binding_id))
            if cursor.fetchone() is not None:
                raise PermissionError("original Core lifecycle history forbids namespace recreation")
    committed = capacity.authority.receiver_transport.load_endpoint(registration.endpoint_id)
    if (committed["registration"]["registration_json"] != registration.model_dump(mode="json")
            or committed["registration"]["node_key_id"] != capacity.config.binding.node_key_id
            or committed["node_public_key"] != capacity.config.binding.node_public_key):
        raise PermissionError("current lifecycle deployment registration differs")


def lifecycle_journal(capacity, *, journal_class=DriverJournal):
    settings = capacity.settings
    if not settings.get("lifecycle_control", False):
        return journal_class(settings["driver_journal"], clock=getattr(capacity, "clock", None))
    path = Path(settings["driver_journal"])
    if settings.get("lifecycle_initialize_journal", False) and path.parent.exists() and not path.is_file():
        raise FileExistsError("existing native namespace has lost its original journal; refusing recreation")
    if settings.get("lifecycle_initialize_journal", False) and not path.parent.exists():
        # This explicit one-time operator setting cannot recreate a lost journal
        # inside an old namespace. The private provisioning API requires mkdir
        # and O_EXCL success for a previously unused directory and file.
        provisioning = True

        def authorize_namespace(namespace, binding_id, binding):
            _namespace_authority(capacity, namespace, binding_id, binding, for_provision=provisioning)

        capacity._lifecycle_reservation = create_capacity_reservation(path.parent,
            binding_id=settings["binding_id"], binding=capacity.binding,
            authorize_current_namespace=authorize_namespace)
        provisioning = False  # The retained live witness now proves this exact original namespace.
        journal = journal_class(path, clock=getattr(capacity, "clock", None))
        preview = journal.preview_lifecycle_adoption()
        journal.adopt_lifecycle_schema(expected_legacy_digest=preview["legacy_digest"])
        return journal
    # Verify with mode=ro before constructing DriverJournal: its legacy
    # constructor intentionally creates tables and cannot establish absence.
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        if DriverJournal._source_schema(connection) != 2:
            raise ValueError("explicit lifecycle journal adoption is required")
    capacity._lifecycle_reservation = None
    return journal_class(path, clock=getattr(capacity, "clock", None))


def attach_lifecycle_controller(capacity):
    settings = capacity.settings
    capacity.authority._receiver_message_wake_policy = lambda endpoint_id: (
        endpoint_id == capacity.config.binding.registration.endpoint_id and settings.get("lifecycle_message_wake", False) is True)
    raw = Path(settings["lifecycle_catalog"]).read_bytes()
    if len(raw) > 2 * 1024 * 1024 or sha256(raw) != settings["lifecycle_catalog_sha256"]:
        raise ValueError("lifecycle ProjectService catalog changed")
    catalog = json.loads(raw)
    projects = ProjectService(SharedService(capacity.authority,
        LocalCredentialAuthenticator(capacity.authority.context)), catalog, profile="engineer")
    core = LifecycleCoreCallbacks(projects, journal_generation=capacity.config.journal_generation)
    account = PrivateReference.model_validate(settings["lifecycle_account_ref"], strict=True)

    def authorize(driver):
        _namespace_authority(capacity, Path(driver.journal.path).parent, driver.binding_id, driver.identity)

    def selected_account(_driver):
        value = account.resolve()
        if not value:
            raise CapacityEvidenceUnavailable("selected lifecycle account binding unavailable")
        return sha256({"selected_account_binding": value})

    def original_profile(origin, seal):
        # Namespace enrollment is current authority. The retained original Core
        # permit supplies historical profile/command provenance; it is never
        # reused as permission for this new resume action.
        authorize(capacity.driver)
        with capacity.authority._connect() as connection:
            rows = connection.execute("SELECT topic,payload FROM outbox WHERE tenant_id=%s AND operation_id=%s "
                "AND topic IN ('communication.receiver.recovery','message.delivery')",
                (capacity.authority.tenant_id, origin.source_ref)).fetchall()
        if len(rows) != 1:
            raise CapacityEvidenceUnavailable("original_restore_core_source_unavailable")
        topic, payload = rows[0]
        data = payload.get("receiver_wake", {}).get("lifecycle") if topic == "message.delivery" else payload.get("lifecycle")
        if not isinstance(data, dict):
            raise CapacityEvidenceUnavailable("original_restore_core_source_unavailable")
        candidates = [data, *data.get("history", [])]
        for candidate in candidates:
            raw = candidate.get("plan")
            if not isinstance(raw, dict) or raw.get("driver_operation_id") != origin.creation_operation_id:
                continue
            plan = LifecyclePlan.model_validate_json(json.dumps(raw), strict=True)
            signed = SignedLifecyclePermit.model_validate_json(json.dumps(candidate["permit"]), strict=True)
            if (signed.permit.plan != plan or plan.source.operation_ref != origin.source_ref
                    or plan.source.command_id != origin.command_id or plan.target.registration != capacity.config.binding.registration
                    or plan.capacity.binding != capacity.driver.identity or plan.capacity.driver_binding_id != capacity.driver.binding_id
                    or plan.capacity.profile_fingerprint != seal["profile_fingerprint"]
                    or candidate.get("first_plan_digest") != signed.permit.semantic_digest):
                raise CapacityEvidenceUnavailable("original_restore_core_profile_changed")
            verify(capacity.config.authority_public_key, signed.signature, signed.permit)
            authorize(capacity.driver)
            return
        raise CapacityEvidenceUnavailable("original_restore_core_plan_unavailable")

    try:
        witness = capture_capacity_profile(capacity.driver, authorize_current=authorize, account_fingerprint=selected_account)
    except CapacityEvidenceUnavailable:
        try:
            witness = recover_capacity_profile(capacity.driver, authorize_current=authorize,
                account_fingerprint=selected_account, authorize_original=original_profile)
        except (CapacityEvidenceUnavailable, DriverRejected, OSError, ValueError):
            # Missing historical trust remains unavailable; never substitute a
            # new native context or infer the old account from a directory name.
            witness = None

    return ReceiverLifecycleNode(capacity.driver, capacity.config, load_owner_signing_key(capacity.config.node_signing_key_path),
        clock=capacity.clock, resolve_original=core.resolve, require_current_execution=core.execution,
        resolve_original_read=core.read, core_session=core.session, profile_witness=witness,
        fresh_capacity_seconds=settings.get("lifecycle_fresh_capacity_seconds", 15),
        reservation_witness=getattr(capacity, "_lifecycle_reservation", None))
