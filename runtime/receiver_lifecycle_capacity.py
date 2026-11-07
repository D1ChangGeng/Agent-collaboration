"""Node-owned read-only capacity evidence; no lifecycle/input permission is issued.

Profile/account witnesses are captured by the trusted Node, not deserialized from
an admission body. Native reads are injected already-authorized message-less
observers. The separately named provisioning helper creates only a new private
directory/empty file; it never creates SQLite tables. Observation creates no
storage, Driver action or process and never guesses secret files. Its SQL
connections are read-only and closed before callbacks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime.codex_driver import BindingIdentity, CodexAppServerDriver, DriverJournal, digest
from runtime.native_input_observations import MAX_CONFIG_BYTES, MAX_SCHEMA_BYTES
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.receiver_contract import native_generation
from runtime.receiver_crypto import sha256
from runtime.receiver_lifecycle_contract import (
    LifecycleCapacityFact,
    OwnedProcessEvidence,
    profile_fingerprint,
)

_WITNESS = object()
_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
_MAX_ROWS = 100000
_READ_RPC = {"initialize", "thread/read", "thread/turns/list", "config/read",
             "experimentalFeature/list", "permissionProfile/list", "mcpServerStatus/list"}


def _birth_identity(info):
    return (info.st_dev, info.st_ino, getattr(info, "st_birthtime_ns", None))


@dataclass(frozen=True)
class CapturedCapacityReservation:
    """Private, process-local proof of a newly provisioned capacity namespace."""
    driver_binding_id: str
    binding: BindingIdentity
    journal_path: str
    evidence_ref: str
    _namespace: Path = field(repr=False)
    _directory_identity: tuple = field(repr=False)
    _file_identity: tuple = field(repr=False)
    _creator_process: int = field(repr=False)
    _authorize_namespace: Callable = field(repr=False, compare=False)
    _capture: object = field(repr=False, compare=False, default=_WITNESS)


def _namespace_authorized(authorize, namespace, binding_id, binding):
    try:
        result = authorize(namespace, binding_id, binding)
        if result is not None and result is not True:
            raise PermissionError
    except Exception as error:
        raise CapacityEvidenceUnavailable("capacity_authorization_denied") from error


def create_capacity_reservation(namespace, *, binding_id, binding, authorize_current_namespace):
    """Explicit provisioning, never called by an observer or existing factory.

    The trusted Node callback must establish that the parent is Node-private and
    the actual binding/enrollment may provision this previously unused namespace.
    Existing namespaces are refused, even if their journal has been lost. The
    deferred production factory must supply this authority; no wire claim does.
    Failure leaves any created namespace for operator diagnosis, never recycling.
    """
    if type(binding) is not BindingIdentity or not callable(authorize_current_namespace):
        raise CapacityEvidenceUnavailable("capacity_reservation_authority_unavailable")
    binding.validate(); _ref(binding_id)
    namespace = Path(namespace)
    if not namespace.is_absolute():
        raise CapacityEvidenceUnavailable("capacity_namespace_not_absolute")
    _namespace_authorized(authorize_current_namespace, namespace, binding_id, binding)
    namespace.mkdir(mode=0o700, parents=False, exist_ok=False)
    directory = namespace.lstat()
    if not stat.S_ISDIR(directory.st_mode) or namespace.is_symlink():
        raise CapacityEvidenceUnavailable("capacity_namespace_unsupported")
    path = namespace / "driver.sqlite"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    try:
        created = os.fstat(descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _namespace_authorized(authorize_current_namespace, namespace, binding_id, binding)
    current = path.lstat()
    if (_birth_identity(directory) != _birth_identity(namespace.lstat())
            or _birth_identity(created) != _birth_identity(current) or not stat.S_ISREG(current.st_mode)
            or current.st_size != 0 or current.st_nlink != 1 or path.is_symlink()):
        raise CapacityEvidenceUnavailable("capacity_namespace_changed_during_creation")
    ref = "capacity-reservation:" + _hash({"binding_id": binding_id, "binding": asdict(binding),
        "namespace": str(namespace), "directory": _birth_identity(directory), "file": _birth_identity(current),
        "creator_process": os.getpid()})
    return CapturedCapacityReservation(binding_id, binding, str(path), ref, namespace,
        _birth_identity(directory), _birth_identity(current), os.getpid(), authorize_current_namespace)


def _reservation_current(driver, witness):
    if (type(witness) is not CapturedCapacityReservation or witness._capture is not _WITNESS
            or witness._creator_process != os.getpid() or witness.driver_binding_id != driver.binding_id
            or witness.binding != driver.identity or Path(witness.journal_path) != Path(driver.journal.path).absolute()
            or Path(witness.journal_path).parent != witness._namespace):
        raise CapacityEvidenceUnavailable("fresh_capacity_provenance_missing")
    _namespace_authorized(witness._authorize_namespace, witness._namespace, driver.binding_id, driver.identity)
    directory, journal = witness._namespace.lstat(), Path(witness.journal_path).lstat()
    if (not stat.S_ISDIR(directory.st_mode) or not stat.S_ISREG(journal.st_mode) or journal.st_nlink != 1
            or witness._namespace.is_symlink() or Path(witness.journal_path).is_symlink()
            or _birth_identity(directory) != witness._directory_identity or _birth_identity(journal) != witness._file_identity):
        raise CapacityEvidenceUnavailable("fresh_capacity_namespace_identity_changed")
    return witness.evidence_ref


class CapacityEvidenceUnavailable(ValueError):
    def __init__(self, reason):
        self.reason_code = reason
        super().__init__("Node capacity evidence is unavailable")


def _hash(value):
    return sha256({"value": value})


def _digest_reference(value):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise CapacityEvidenceUnavailable("account_or_profile_evidence_unavailable")
    return value


def _ref(value):
    if type(value) is not str or not 1 <= len(value) <= 512 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CapacityEvidenceUnavailable("capacity_reference_unavailable")
    return value


def _now(driver):
    value = driver.clock.observation_time() if driver.clock is not None else datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CapacityEvidenceUnavailable("capacity_clock_unavailable")
    return value


def _session(driver):
    return driver.thread_id if isinstance(driver, CodexAppServerDriver) else driver.session_id


def _identity(driver):
    identity = driver.identity
    if type(identity) is not BindingIdentity:
        raise CapacityEvidenceUnavailable("capacity_binding_unavailable")
    identity.validate()
    owned = driver.owned
    return (driver.binding_id, asdict(identity), driver.ownership, getattr(driver, "thread_id", None),
            driver.session_id, id(driver.client), id(owned), getattr(owned, "birth_ref", None),
            getattr(owned, "containment_id", None), getattr(getattr(owned, "process", None), "pid", None),
            id(driver.profile), id(driver.journal), id(driver.clock), id(driver.supervisor), id(driver._claim_token), driver._claim_fd,
            id(driver._claim_journal), driver.journal.path)


def _claim(driver):
    journal = driver.journal
    if (not isinstance(journal, DriverJournal) or journal is not driver._claim_journal
            or type(driver._claim_fd) is not int or driver._claim_token is None):
        raise CapacityEvidenceUnavailable("kernel_ownership_unavailable")
    journal.validate_claim(driver._claim_token, driver.binding_id, driver._claim_fd)
    token = driver._claim_token
    expected = str(Path(journal.path + "." + digest(driver.binding_id) + ".lock").absolute())
    if token.path != expected:
        raise CapacityEvidenceUnavailable("journal_claim_path_changed")
    return "kernel-claim:" + _hash({"binding": driver.binding_id, "identity": asdict(driver.identity),
        "kernel_file": token._identity, "node_process": token.process_id, "claim": id(token)})


def _guard(driver, authorize, expected=None):
    # The same callback convention as current Node authorizers: success is None
    # or explicit True; all other return values and exceptions fail closed.
    try:
        result = authorize(driver)
    except Exception as error:
        raise CapacityEvidenceUnavailable("capacity_authorization_denied") from error
    if result is not None and result is not True:
        raise CapacityEvidenceUnavailable("capacity_authorization_denied")
    if expected is not None and _identity(driver) != expected:
        raise CapacityEvidenceUnavailable("capacity_binding_changed")
    return _claim(driver)


def _file(path, maximum):
    path = Path(path)
    info = path.lstat()
    if not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise CapacityEvidenceUnavailable("profile_file_unsupported")
    if not 0 <= info.st_size <= maximum:
        raise CapacityEvidenceUnavailable("profile_file_budget_exceeded")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        hasher = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            hasher.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    # Windows Python exposes creation time as path-stat ctime while handle-stat
    # ctime can be the change time. Compare each clock only within its own API;
    # inode/size/mtime/mode/link identity must still agree across both APIs.
    if (_file_identity(info) != _file_identity(before) or _file_stamp(before) != _file_stamp(after)
            or _file_identity(after) != _file_identity(current) or _file_stamp(info) != _file_stamp(current)):
        raise CapacityEvidenceUnavailable("profile_file_changed")
    return {"path": str(path), "sha256": hasher.hexdigest()}, _file_stamp(current)


def _file_identity(info):
    # Windows path stat derives executable bits from the filename suffix;
    # fstat has no filename and reports those bits unset. Retain all type and
    # read/write bits across APIs, and the full mode in each API's own stamp.
    mode = info.st_mode & ~0o111 if os.name == "nt" else info.st_mode
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, mode, info.st_nlink,
            getattr(info, "st_birthtime_ns", None))


def _file_stamp(info):
    return (*_file_identity(info), info.st_mode, info.st_ctime_ns)


def _profile(driver, authorize, expected, account_reader):
    if not callable(account_reader):
        raise CapacityEvidenceUnavailable("account_evidence_unavailable")
    profile = driver.profile
    environment = copy.deepcopy(profile.environment)
    if type(environment) is not dict or any(type(key) is not str or type(value) is not str for key, value in environment.items()):
        raise CapacityEvidenceUnavailable("selected_environment_unavailable")
    captured = copy.deepcopy(profile.binding())
    files, stamps = {}, {}
    config = Path(profile.codex_home) / "config.toml" if isinstance(driver, CodexAppServerDriver) else profile.config_path
    for label, path, maximum, pinned in (
        ("executable", profile.executable, _MAX_EXECUTABLE_BYTES, profile.executable_sha256),
        ("schema", profile.schema_path, MAX_SCHEMA_BYTES, profile.schema_sha256),
        ("configuration", config, MAX_CONFIG_BYTES, profile.config_sha256),
    ):
        evidence, stamp = _file(path, maximum)
        _guard(driver, authorize, expected)
        if evidence["sha256"] != _digest_reference(pinned):
            raise CapacityEvidenceUnavailable("captured_profile_bytes_mismatch")
        files[label], stamps[str(path)] = evidence, stamp
    profile.validate()
    _guard(driver, authorize, expected)
    account = _digest_reference(account_reader(driver))
    _guard(driver, authorize, expected)
    captured.update(capacity_file_evidence=files, account_fingerprint=account)
    if environment != driver.profile.environment or captured != {
            **copy.deepcopy(driver.profile.binding()), "capacity_file_evidence": files, "account_fingerprint": account}:
        raise CapacityEvidenceUnavailable("captured_profile_changed")
    return profile_fingerprint(captured, environment), stamps, account, _hash({"profile": profile.binding(), "environment": environment})


@dataclass(frozen=True)
class CapturedCapacityProfile:
    """Private Node capture. This object is not a wire/permission model."""
    driver_binding_id: str
    binding: BindingIdentity
    fingerprint: str
    evidence_ref: str
    account_fingerprint: str = field(repr=False)
    _memory_fingerprint: str = field(repr=False)
    _journal_identity: tuple = field(repr=False)
    _driver: object = field(repr=False, compare=False)
    _profile: object = field(repr=False, compare=False)
    _account_reader: Callable = field(repr=False, compare=False)
    _capture: object = field(repr=False, compare=False, default=_WITNESS)


def capacity_profile_seal(witness):
    if type(witness) is not CapturedCapacityProfile or witness._capture is not _WITNESS:
        raise CapacityEvidenceUnavailable("captured_profile_witness_missing")
    return {"schema_version": "acs-native-restore-profile/1", "profile_fingerprint": witness.fingerprint,
            "account_fingerprint": witness.account_fingerprint, "memory_fingerprint": witness._memory_fingerprint}


def capture_capacity_profile(driver, *, authorize_current, account_fingerprint):
    """Capture actual Node-selected files/env and account digest, never auth paths.

    Node integration must capture the launch baseline at its own trusted binding
    boundary and retain this object. This helper cannot reconstruct an original
    process environment from a caller's digest or a guessed account filename.
    """
    if not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver)) or not callable(authorize_current):
        raise CapacityEvidenceUnavailable("unsupported_capacity_driver")
    with driver._lock:
        _guard(driver, authorize_current)
        before = _identity(driver)
        history = _journal(driver)
        _guard(driver, authorize_current, before)
        if (driver.ownership != "unbound" or driver.owned is not None or driver.client is not None
                or _session(driver) is not None or driver.session_id is not None
                or history["state"] != "clear" or history["prior_effect"]):
            raise CapacityEvidenceUnavailable("profile_baseline_requires_pre_effect_capacity")
        fingerprint, stamps, account, memory = _profile(driver, authorize_current, before, account_fingerprint)
        after = _journal(driver)
        _guard(driver, authorize_current, before)
        _stamps_current(stamps)
        if history["identity"] != after["identity"] or history["mutation_digest"] != after["mutation_digest"]:
            raise CapacityEvidenceUnavailable("journal_changed_during_profile_capture")
        return CapturedCapacityProfile(driver.binding_id, driver.identity, fingerprint,
            "capacity-profile:" + fingerprint, account, memory, history["identity"], driver, driver.profile, account_fingerprint)


def recover_capacity_profile(driver, *, authorize_current, account_fingerprint, authorize_original):
    """Reconstruct only a positively stopped, Core-attested original context.

    The old account/environment/file fingerprint is checked against the retained
    original Core permit before any Driver state changes. Unknown process stops
    or historical creation outcomes cannot be retroactively upgraded.
    """
    from runtime.native_restore_origin import load_stopped_origin

    with driver._lock:
        _guard(driver, authorize_current)
        before = _identity(driver)
        history = _journal(driver)
        origin = load_stopped_origin(driver)
        fingerprint, stamps, account, memory = _profile(driver, authorize_current, before, account_fingerprint)
        seal = {"schema_version": "acs-native-restore-profile/1", "profile_fingerprint": fingerprint,
                "account_fingerprint": account, "memory_fingerprint": memory}
        if origin.profile_seal is not None and dict(origin.profile_seal) != seal:
            raise CapacityEvidenceUnavailable("original_restore_profile_changed")
        if not callable(authorize_original) or authorize_original(origin, seal) is not None:
            raise CapacityEvidenceUnavailable("original_restore_core_attestation_unavailable")
        _guard(driver, authorize_current, before)
        _stamps_current(stamps)
        after = _journal(driver)
        if history["identity"] != after["identity"] or history["mutation_digest"] != after["mutation_digest"]:
            raise CapacityEvidenceUnavailable("original_restore_journal_changed")
        driver._restoration_origin = origin
        if isinstance(driver, CodexAppServerDriver):
            driver.thread_id, driver.session_id = origin.native_session_ref, origin.provider_session_ref
        else:
            driver.session_id = origin.native_session_ref
        driver.ownership = "exclusive_reserved_restore"
        return CapturedCapacityProfile(driver.binding_id, driver.identity, fingerprint, "capacity-profile:" + fingerprint,
            account, memory, history["identity"], driver, driver.profile, account_fingerprint)


def _possible_effect(kind, body):
    if kind in {"process_intent", "process_dispatch"}:
        return True
    if kind in {"rpc_intent", "rpc_dispatch"}:
        return body.get("method") not in _READ_RPC
    if kind in {"http_intent", "http_dispatch"}:
        return body.get("method") != "GET"
    return kind not in {"rpc_response", "http_response", "native_event", "notification_intent",
                        "private_auth_staged", "native_environment_observed"}


def _journal(driver):
    path = Path(driver.journal.path).absolute()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise CapacityEvidenceUnavailable("journal_history_unavailable")
    # mode=ro never creates a missing DB. One UNION statement captures operations
    # and events in the same SQLite read snapshot; no transaction crosses I/O.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=2)
    try:
        schema = driver.journal._source_schema(connection)
        if schema != 2:
            raise CapacityEvidenceUnavailable("explicit_lifecycle_journal_adoption_required")
        driver.journal._verify_lifecycle_schema(connection)
        extra = "source_kind,source_ref" if schema == 2 else "NULL,NULL"
        rows = connection.execute("SELECT 0,operation_id,binding_id,command_id,message_id,action,input_hash,input_json,state,result_json," + extra + ",NULL,NULL,NULL,NULL "
            "FROM driver_operations UNION ALL SELECT 1,operation_id,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,kind,body,observed_at,sequence "
            "FROM driver_events UNION ALL SELECT 2,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
            "(SELECT seq FROM sqlite_sequence WHERE name='driver_events') LIMIT ?", (_MAX_ROWS + 1,)).fetchall()
        if len(rows) > _MAX_ROWS or driver.journal._source_schema(connection) != schema:
            raise CapacityEvidenceUnavailable("journal_history_budget_or_schema_changed")
    finally:
        connection.close()
    current = path.lstat()
    if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
        raise CapacityEvidenceUnavailable("journal_history_replaced")
    operations, events, sequences, frontier = {}, [], [], []
    for row in rows:
        if row[0] == 0:
            operation = tuple(row[1:10]) + (tuple(row[10:12]) if schema == 2 else ())
            driver.journal._verify_operation_row(operation, schema)
            if operation[7] not in {"intent", "uncertain", "acknowledged", "rejected", "deferred"}:
                raise CapacityEvidenceUnavailable("journal_operation_state_unavailable")
            if operation[8] is not None and type(json.loads(operation[8])) is not dict:
                raise CapacityEvidenceUnavailable("journal_operation_result_corrupt")
            operations[row[1]] = operation
        elif row[0] == 1:
            try:
                body = json.loads(row[13])
            except (ValueError, TypeError) as error:
                raise CapacityEvidenceUnavailable("journal_event_corrupt") from error
            if type(body) is not dict or type(row[12]) is not str or not row[12]:
                raise CapacityEvidenceUnavailable("journal_event_corrupt")
            observed = datetime.fromisoformat(row[14])
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise CapacityEvidenceUnavailable("journal_event_clock_unavailable")
            events.append((row[1], row[12], body, row[14]))
            sequences.append(row[15])
        else:
            frontier.append(row[15])
    if (len(frontier) != 1 or any(type(value) is not int or value < 1 for value in sequences)
            or sorted(sequences) != list(range(1, len(sequences) + 1))
            or frontier[0] != (len(sequences) or None)):
        raise CapacityEvidenceUnavailable("journal_event_history_incomplete")
    selected = [row for row in operations.values() if row[1] == driver.binding_id]
    uncertain = any(row[7] in {"intent", "uncertain"} for row in selected)
    mutations, started = [], []
    for operation_id, kind, body, observed in events:
        if _possible_effect(kind, body):
            operation = operations.get(operation_id)
            if operation is None:
                raise CapacityEvidenceUnavailable("journal_orphan_possible_effect")
            if operation[1] == driver.binding_id:
                mutations.append((operation_id, kind, body, observed))
                if kind == "process_started":
                    source = json.loads(operation[6])
                    if ((operation[4] != "spawn" and not (operation[4] == "resume" and source["payload"].get("restore_process") is True))
                            or source["payload"].get("binding") != asdict(driver.identity)):
                        raise CapacityEvidenceUnavailable("journal_process_scope_mismatch")
                    started.append({"pid": body.get("pid"), "birth_ref": body.get("birth_ref"),
                        "containment_id": body.get("containment_id"), "profile": source["payload"].get("profile")})
    # A successful mutating row without process/RPC events is missing history,
    # not proof that an absent in-memory handle means a fresh capacity.
    prior = bool(mutations) or any(row[7] not in {"rejected", "deferred"} for row in selected)
    return {"state": "unresolved" if uncertain else "clear", "prior_effect": prior,
        "identity": _birth_identity(info),
        "evidence": "driver-journal:" + _hash(rows), "mutation_digest": _hash([selected, mutations]),
        "has_operation_history": bool(selected), "process_starts": started}


def _owned_process(driver):
    owned = driver.owned
    if owned is None or driver.supervisor is None or not callable(getattr(driver.supervisor, "inspect", None)):
        raise CapacityEvidenceUnavailable("owned_process_evidence_unsupported")
    proof = driver.supervisor.inspect(owned)
    pid = getattr(getattr(owned, "process", None), "pid", None)
    # Exact predicate already used by NativeInputObservations, with the actual
    # supervised handle's PID retained as identity rather than process-name lookup.
    if (type(pid) is not int or pid < 1 or type(proof) is not dict or proof.get("verified") is not True
            or proof.get("root_exited") is not False or proof.get("birth_ref") != owned.birth_ref
            or proof.get("containment_id") != owned.containment_id
            or proof.get("root_pid", pid) != pid or proof.get("pid", pid) != pid):
        raise CapacityEvidenceUnavailable("owned_process_evidence_unavailable")
    evidence = "owned-process:" + _hash(proof)
    return OwnedProcessEvidence(pid=pid, birth_ref=_ref(owned.birth_ref), containment_id=_ref(owned.containment_id), evidence_ref=evidence)


def _native(driver, value, now):
    if type(value) is not dict:
        raise CapacityEvidenceUnavailable("native_readback_unavailable")
    session = _ref(_session(driver))
    if (value.get("binding_id") != driver.binding_id or value.get("native_session_ref") != session
            or value.get("ownership") != "exclusive_owned" or value.get("dedicated_input") is not True
            or value.get("schema_verified") is not True or value.get("source") != "native_api"):
        raise CapacityEvidenceUnavailable("native_readback_scope_unavailable")
    for name in ("protocol_digest", "config_digest"):
        _digest_reference(value.get(name))
    evidence = _ref(value.get("evidence_ref"))
    if not evidence.startswith("native-input-observation:"):
        raise CapacityEvidenceUnavailable("native_readback_evidence_unavailable")
    _digest_reference(evidence.removeprefix("native-input-observation:"))
    observed, expires = datetime.fromisoformat(value["observed_at"]), datetime.fromisoformat(value["expires_at"])
    if (observed.tzinfo is None or expires.tzinfo is None or not observed <= now < expires
            or not timedelta(0) < expires - observed <= timedelta(seconds=2)):
        raise CapacityEvidenceUnavailable("native_readback_expired")
    axes = value.get("axes", {})
    for axis, expected in (("connection", "connected"), ("process", "present"), ("session", "present")):
        item = axes.get(axis, {})
        if item.get("knowledge") != "observed" or item.get("value") != expected or item.get("evidence_ref") != evidence:
            raise CapacityEvidenceUnavailable("native_readback_not_positive")
    input_axis, blocker = axes.get("input", {}), axes.get("blocker", {})
    input_state = input_axis.get("value") if input_axis.get("knowledge") == "observed" and input_axis.get("evidence_ref") == evidence else "unknown"
    block = blocker.get("value") if blocker.get("knowledge") == "observed" and blocker.get("evidence_ref") == evidence else "unknown"
    return session, input_state if input_state in {"ready", "busy"} else "unknown", block if block in {"none", "approval", "question", "draft"} else "unknown", evidence


def _stamps_current(stamps):
    for path, stamp in stamps.items():
        info = Path(path).lstat()
        if stamp != _file_stamp(info):
            raise CapacityEvidenceUnavailable("profile_file_changed_after_readback")


def _process_history(driver, history, process):
    matching = [item for item in history["process_starts"] if
        (item["pid"], item["birth_ref"], item["containment_id"], item["profile"]) ==
        (process.pid, process.birth_ref, process.containment_id, driver.profile.binding())]
    if len(matching) != 1:
        raise CapacityEvidenceUnavailable("owned_process_journal_identity_unavailable")


def observe_receiver_capacity(driver, *, authorize_current, profile_witness=None, reservation_witness=None,
                              native_readback=None, ttl_seconds=2, fresh_ttl_seconds=None):
    """Read actual Node capacity. Unknown never grants mutation or makes a Session.

    native_readback(driver) must perform only the actual already-authorized,
    message-less Native read and return NativeInputObservations' existing shape.
    No legacy message/Attempt identity is manufactured to call that observer.
    """
    if not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver)) or not callable(authorize_current):
        raise TypeError("an actual Driver and trusted current-capacity authorizer are required")
    if type(ttl_seconds) not in (int, float) or not 0 < ttl_seconds <= 5:
        raise ValueError("capacity evidence has a bounded positive lifetime")
    if fresh_ttl_seconds is not None and (type(fresh_ttl_seconds) not in (int, float) or not 0 < fresh_ttl_seconds <= 30):
        raise ValueError("fresh private reservation lifetime must be within the lifecycle transport bound")
    with driver._lock:
        before = _identity(driver)
        result = {"state": "unknown", "driver_binding_id": driver.binding_id, "binding": driver.identity,
            "profile_fingerprint": None, "profile_evidence_ref": None, "ownership": "unknown", "journal_state": "unknown",
            "kernel_claim_ref": None, "journal_evidence_ref": None, "absence_evidence_ref": None, "process": None,
            "native_session_ref": None, "provider_generation": None, "input_state": "unknown", "blocker": "unknown", "reason_code": "capacity_evidence_unavailable"}
        evidence = []
        native = None
        process_observed = None
        final_now = None
        valid_until = None
        stopped = False
        try:
            claim = _guard(driver, authorize_current, before)
            result["kernel_claim_ref"] = claim; evidence.append(claim)
            history = _journal(driver)
            result.update(journal_state=history["state"], journal_evidence_ref=history["evidence"]); evidence.append(history["evidence"])
            _guard(driver, authorize_current, before)
            if driver.owned is not None:
                poll = getattr(driver.owned.process, "poll", None)
                stopped = callable(poll) and poll() is not None
                if stopped:
                    from runtime.native_restore import stopped_process

                    process = OwnedProcessEvidence(**stopped_process(driver))
                else:
                    process = _owned_process(driver)
                _guard(driver, authorize_current, before)
                result["process"] = process; evidence.append(process.evidence_ref)
            elif driver.ownership == "exclusive_reserved_restore":
                from runtime.native_restore import stopped_process

                stopped = True
                process = OwnedProcessEvidence(**stopped_process(driver))
                result["process"] = process; evidence.append(process.evidence_ref)
            witness = profile_witness
            if (type(witness) is not CapturedCapacityProfile or witness._capture is not _WITNESS
                    or witness._driver is not driver or witness._profile is not driver.profile
                    or witness.driver_binding_id != driver.binding_id or witness.binding != driver.identity
                    or witness.evidence_ref != "capacity-profile:" + witness.fingerprint):
                raise CapacityEvidenceUnavailable("captured_profile_witness_missing")
            if history["identity"] != witness._journal_identity:
                raise CapacityEvidenceUnavailable("captured_journal_replaced")
            fingerprint, stamps, account, memory = _profile(driver, authorize_current, before, witness._account_reader)
            if fingerprint != witness.fingerprint or account != witness.account_fingerprint or memory != witness._memory_fingerprint:
                raise CapacityEvidenceUnavailable("captured_profile_changed")
            result.update(profile_fingerprint=fingerprint, profile_evidence_ref=witness.evidence_ref); evidence.append(witness.evidence_ref)
            if stopped:
                from runtime.native_restore import restoration_history

                original = restoration_history(driver)
                _guard(driver, authorize_current, before)
                selected = _ref(_session(driver))
                result.update(state="stopped", ownership="exclusive_owned" if driver.owned is not None else "exclusive_reserved", native_session_ref=selected,
                    provider_generation=native_generation(driver.binding_id, asdict(driver.identity), selected),
                    input_state="unknown", blocker="unknown", reason_code=None)
                if original["evidence_ref"] != process.evidence_ref:
                    raise CapacityEvidenceUnavailable("original_stopped_process_changed")
            elif driver.owned is None and driver.client is None and _session(driver) is None and driver.session_id is None:
                reservation_ref = _reservation_current(driver, reservation_witness)
                _guard(driver, authorize_current, before)
                if driver.ownership != "unbound":
                    raise CapacityEvidenceUnavailable("fresh_driver_state_not_reserved")
                if history["state"] != "clear" or history["prior_effect"]:
                    raise CapacityEvidenceUnavailable("prior_native_effect_not_fresh")
                after = _journal(driver); _guard(driver, authorize_current, before)
                if after["identity"] != history["identity"] or after["mutation_digest"] != history["mutation_digest"]:
                    raise CapacityEvidenceUnavailable("journal_changed_during_observation")
                absence = "capacity-absence:" + _hash({"driver": before, "claim": claim, "history": after["evidence"], "profile": fingerprint,
                    "reservation": reservation_ref})
                result.update(state="fresh", ownership="exclusive_reserved", input_state="not_started", blocker="none",
                    absence_evidence_ref=absence, journal_evidence_ref=after["evidence"], reason_code=None)
                evidence.extend((absence, after["evidence"], reservation_ref))
            else:
                if driver.ownership != "exclusive_owned" or driver.owned is None or driver.client is None:
                    raise CapacityEvidenceUnavailable("existing_driver_ownership_unsupported")
                if not history["has_operation_history"] or not callable(native_readback):
                    raise CapacityEvidenceUnavailable("existing_native_history_or_readback_missing")
                _process_history(driver, history, result["process"])
                _guard(driver, authorize_current, before)
                native = native_readback(driver)
                _guard(driver, authorize_current, before)
                process = _owned_process(driver); process_observed = _now(driver); _guard(driver, authorize_current, before)
                after = _journal(driver)
                if after["identity"] != history["identity"] or after["mutation_digest"] != history["mutation_digest"]:
                    raise CapacityEvidenceUnavailable("journal_changed_during_native_read")
                selected, input_state, blocker, native_ref = _native(driver, native, _now(driver))
                result.update(state="existing", ownership="exclusive_owned", process=process, native_session_ref=selected,
                    provider_generation=native_generation(driver.binding_id, asdict(driver.identity), selected), input_state=input_state,
                    blocker=blocker, journal_state=after["state"], journal_evidence_ref=after["evidence"], reason_code=None)
                evidence.extend((process.evidence_ref, after["evidence"], native_ref))
            # Check byte identities again after every callback/wait without a
            # second large executable read inside the Native evidence lifetime.
            if _digest_reference(witness._account_reader(driver)) != witness.account_fingerprint:
                raise CapacityEvidenceUnavailable("account_changed_after_readback")
            _guard(driver, authorize_current, before)
            if _hash({"profile": driver.profile.binding(), "environment": driver.profile.environment}) != witness._memory_fingerprint:
                raise CapacityEvidenceUnavailable("profile_environment_changed_after_readback")
            _stamps_current(stamps)
            final_history = _journal(driver)
            if final_history["identity"] != history["identity"] or final_history["mutation_digest"] != history["mutation_digest"]:
                raise CapacityEvidenceUnavailable("journal_changed_after_callbacks")
            result.update(journal_state=final_history["state"], journal_evidence_ref=final_history["evidence"])
            evidence.append(final_history["evidence"])
            _guard(driver, authorize_current, before)
            if result["state"] == "fresh":
                _reservation_current(driver, reservation_witness)
                _guard(driver, authorize_current, before)
            elif result["state"] == "stopped":
                if restoration_history(driver)["evidence_ref"] != result["process"].evidence_ref:
                    raise CapacityEvidenceUnavailable("original_stopped_process_changed")
                _guard(driver, authorize_current, before)
            _stamps_current(stamps)
            if _hash({"profile": driver.profile.binding(), "environment": driver.profile.environment}) != witness._memory_fingerprint:
                raise CapacityEvidenceUnavailable("profile_environment_changed_after_callbacks")
            _claim(driver)
            if _identity(driver) != before:
                raise CapacityEvidenceUnavailable("capacity_binding_changed")
            final_now = _now(driver)
            lifetime = fresh_ttl_seconds if result["state"] in {"fresh", "stopped"} and fresh_ttl_seconds is not None else ttl_seconds
            valid_until = final_now + timedelta(seconds=lifetime)
            if native is not None:
                _native(driver, native, final_now)
                if process_observed is None or not timedelta(0) <= final_now - process_observed < timedelta(seconds=ttl_seconds):
                    raise CapacityEvidenceUnavailable("owned_process_evidence_expired")
                valid_until = min(valid_until, datetime.fromisoformat(native["expires_at"]), process_observed + timedelta(seconds=ttl_seconds))
        except Exception as error:  # noqa: BLE001 - unavailable evidence must never issue mutable eligibility.
            result.update(state="unknown", absence_evidence_ref=None, input_state="unknown", blocker="unknown",
                          reason_code=error.reason_code if isinstance(error, CapacityEvidenceUnavailable) else "capacity_evidence_unavailable")
            if result["reason_code"] == "capacity_authorization_denied":
                result.update(profile_fingerprint=None, profile_evidence_ref=None, ownership="unknown", journal_state="unknown",
                    kernel_claim_ref=None, journal_evidence_ref=None, process=None, native_session_ref=None, provider_generation=None)
                evidence.clear()
        if final_now is None:
            try:
                final_now = _now(driver)
            except Exception:  # noqa: BLE001 - unknown clock evidence never grants mutation.
                final_now = datetime.now(UTC); result.update(state="unknown", reason_code="capacity_clock_unavailable", absence_evidence_ref=None)
        if valid_until is None or valid_until <= final_now:
            valid_until = final_now + timedelta(seconds=ttl_seconds)
        return LifecycleCapacityFact(**result, evidence_refs=tuple(dict.fromkeys(evidence)), observed_at=final_now,
                                     valid_until=valid_until)
