"""Recover a stopped Native context from retained, verified journal facts.

No process is adopted by PID/name. Only a positive original owned-process stop
receipt permits an offline context reservation. Missing stop, partial history,
another binding or an uncertain creation stays unavailable.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType

from runtime.codex_driver import DriverRejected

_CAPTURE = object()


def journal_identity(path):
    info = Path(path).lstat()
    return info.st_dev, info.st_ino, getattr(info, "st_birthtime_ns", None)


@dataclass(frozen=True)
class CapturedStoppedOrigin:
    binding_id: str
    binding: object
    native_session_ref: str
    provider_session_ref: str | None
    process: dict
    creation_operation_id: str
    source_ref: str
    command_id: str
    stop_operation_id: str
    profile_seal: dict | None
    _driver: object = field(repr=False, compare=False)
    _journal: object = field(repr=False, compare=False)
    _journal_identity: tuple = field(repr=False, compare=False)
    _capture: object = field(repr=False, compare=False, default=_CAPTURE)

    def __post_init__(self):
        object.__setattr__(self, "process", MappingProxyType(dict(self.process)))
        if self.profile_seal is not None:
            object.__setattr__(self, "profile_seal", MappingProxyType(dict(self.profile_seal)))


def assert_origin(driver):
    origin = getattr(driver, "_restoration_origin", None)
    if (type(origin) is not CapturedStoppedOrigin or origin._capture is not _CAPTURE
            or origin._driver is not driver or origin._journal is not driver.journal
            or origin.binding_id != driver.binding_id or origin.binding != driver.identity
            or journal_identity(driver.journal.path) != origin._journal_identity
            or (getattr(driver, "thread_id", None) or driver.session_id) != origin.native_session_ref):
        raise DriverRejected("retained original Native restoration witness is unavailable")
    driver.journal.validate_claim(driver._claim_token, driver.binding_id, driver._claim_fd)
    return origin


def load_stopped_origin(driver):
    if (driver.owned is not None or driver.client is not None or driver.ownership != "unbound"
            or getattr(driver, "thread_id", None) is not None or driver.session_id is not None):
        raise DriverRejected("offline restoration capture requires an unbound claimed Driver")
    driver.journal.validate_claim(driver._claim_token, driver.binding_id, driver._claim_fd)
    identity = journal_identity(driver.journal.path)
    with driver.journal._connect() as connection:
        connection.execute("BEGIN")
        driver.journal._verify_lifecycle_schema(connection)
        rows = connection.execute("SELECT " + driver.journal._operation_columns(2) +
            " FROM driver_operations WHERE binding_id=? LIMIT 10001", (driver.binding_id,)).fetchall()
        starts = connection.execute("SELECT sequence,operation_id,body FROM driver_events "
            "WHERE kind='process_started' ORDER BY sequence DESC LIMIT 10001").fetchall()
        if len(rows) > 10000 or len(starts) > 10000:
            raise DriverRejected("offline restoration evidence exceeds its bounded budget")
        operations = {}
        for row in rows:
            driver.journal._verify_operation_row(row, 2)
            body = json.loads(row[6])
            if body["payload"].get("binding") != asdict(driver.identity):
                raise DriverRejected("original Native restoration binding differs")
            if row[7] in {"intent", "uncertain"} and row[4] != "invoke":
                raise DriverRejected("uncertain Native creation/resume cannot be adopted")
            operations[row[0]] = (row, body, json.loads(row[8]) if row[8] else None)
        selected = next(((operation_id, json.loads(raw)) for _sequence, operation_id, raw in starts
                         if operation_id in operations), None)
        if selected is None:
            raise DriverRejected("original owned Native process history is unavailable")
        operation_id, process = selected
        row, body, created = operations[operation_id]
        if (row[7] != "acknowledged" or not isinstance(created, dict) or row[4] not in {"spawn", "resume"}
                or body["payload"].get("profile") != driver.profile.binding()
                or body.get("source_kind") != "receiver_lifecycle" or not body.get("source_ref")):
            raise DriverRejected("original Native creation acknowledgement is unavailable")
        responses = dict(connection.execute("SELECT operation_id,MAX(sequence) FROM driver_events "
            "WHERE kind IN ('rpc_response','http_response') GROUP BY operation_id").fetchall())
        contexts = [(responses.get(key, 0), result) for key, (record, _input, result) in operations.items()
                    if record[7] == "acknowledged" and record[4] in {"spawn", "resume", "replace_session"}
                    and isinstance(result, dict) and result.get("ownership") == "exclusive_owned"]
        if not contexts:
            raise DriverRejected("original Native context acknowledgement is unavailable")
        _sequence, context = max(contexts, key=lambda item: item[0])
        session = context.get("thread_id") if driver.harness == "codex" else context.get("native_session_id")
        if not isinstance(session, str) or not session or context.get("binding") != asdict(driver.identity):
            raise DriverRejected("original Native context identity is unavailable")
        stops = []
        for key, (record, _input, result) in operations.items():
            if record[4] != "terminate" or record[7] != "acknowledged" or not isinstance(result, dict):
                continue
            proof = result.get("supervisor_proof", {})
            reference = result.get("thread_id") if driver.harness == "codex" else result.get("native_session_id")
            if (result.get("receipt_layer") in {"process_tree_terminated", "process_group_terminated"}
                    and result.get("ownership") == "exclusive_owned" and reference == session
                    and result.get("binding") == asdict(driver.identity) and proof.get("verified") is True
                    and proof.get("root_exited") is True and proof.get("remaining_pids") == []
                    and proof.get("birth_ref") == process.get("birth_ref")
                    and proof.get("containment_id") == process.get("containment_id")
                    and proof.get("root_pid", process.get("pid")) == process.get("pid")
                    and (proof.get("scope") != "owned_process_group" or proof.get("remaining_group_members") == [])):
                stops.append(key)
        if not stops or any(not isinstance(process.get(k), (str, int)) for k in ("pid", "birth_ref", "containment_id")):
            raise DriverRejected("original owned Native process has no verified complete stop receipt")
    if journal_identity(driver.journal.path) != identity:
        raise DriverRejected("original Native restoration journal changed")
    return CapturedStoppedOrigin(driver.binding_id, driver.identity, session, context.get("session_id"),
        {k: process[k] for k in ("pid", "birth_ref", "containment_id")}, operation_id,
        body["source_ref"], row[2], stops[-1], body["payload"].get("capacity_profile"), driver, driver.journal, identity)
