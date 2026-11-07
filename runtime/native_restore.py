"""Original owned-session transport restoration; never replacement or input replay.

The existing signed lifecycle capability authorizes the effect. These helpers
only establish the exact stopped process and retained journal provenance; a
missing/unknown history or an unverified surviving process fails closed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict


def stopped_process(driver):
    from runtime.codex_driver import DriverRejected

    owned = driver.owned
    if owned is None and driver.ownership == "exclusive_reserved_restore":
        from runtime.native_restore_origin import assert_origin

        origin = assert_origin(driver)
        identity = dict(origin.process)
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return identity | {"evidence_ref": "stopped-process:" + hashlib.sha256(canonical.encode()).hexdigest()}
    if (driver.ownership != "exclusive_owned" or owned is None or driver.supervisor is None
            or not callable(getattr(driver.supervisor, "inspect", None))
            or not callable(getattr(driver.supervisor, "launch", None))):
        raise DriverRejected("restoration requires the original exclusive owned process")
    pid = getattr(owned.process, "pid", None)
    proof = driver.supervisor.inspect(owned)
    if (type(pid) is not int or pid <= 0 or owned.process.poll() is None or not isinstance(proof, dict)
            or proof.get("verified") is not True or proof.get("root_exited") is not True
            or proof.get("root_pid", pid) != pid or proof.get("pid", pid) != pid
            or proof.get("birth_ref") != owned.birth_ref or proof.get("containment_id") != owned.containment_id
            or proof.get("remaining_pids") != []
            or proof.get("scope") == "owned_process_group" and proof.get("remaining_group_members") != []):
        raise DriverRejected("restoration requires verified termination of the original owned containment")
    identity = {"pid": pid, "birth_ref": owned.birth_ref, "containment_id": owned.containment_id}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return identity | {"evidence_ref": "stopped-process:" + hashlib.sha256(canonical.encode()).hexdigest()}


def restoration_history(driver, *, exclude_operation_id=None):
    """Prove original creation; only same-session uncertain inputs may be queried.

    An uncertain create/resume or another Session still blocks restoration. A
    same-session invoke remains uncertain and fenced throughout reconnection;
    the restoration capability cannot call turn/start or POST a prompt.
    """
    from runtime.codex_driver import DriverRejected

    session = getattr(driver, "thread_id", None) or driver.session_id
    if not isinstance(session, str) or not session:
        raise DriverRejected("restoration requires an existing exact Native session")
    process = stopped_process(driver)
    with driver.journal._connect() as connection:
        schema = driver.journal._source_schema(connection)
        if schema != 2:
            raise DriverRejected("restoration requires explicit lifecycle journal adoption")
        driver.journal._verify_lifecycle_schema(connection)
        rows = connection.execute("SELECT " + driver.journal._operation_columns(schema) +
            " FROM driver_operations WHERE binding_id=? LIMIT 10001", (driver.binding_id,)).fetchall()
        if len(rows) > 10000:
            raise DriverRejected("restoration journal evidence exceeds its bounded budget")
        known_session = False
        process_origin = False
        for row in rows:
            driver.journal._verify_operation_row(row, schema)
            body = json.loads(row[6])
            if row[0] != exclude_operation_id and row[7] in {"intent", "uncertain"}:
                original_session = body["payload"].get("thread_id") if driver.harness == "codex" else body["payload"].get("native_session_id")
                if (row[4] != "invoke" or original_session != session
                        or body["payload"].get("binding") != asdict(driver.identity)):
                    raise DriverRejected("unresolved original operation prevents Native transport restoration")
            if body["payload"].get("binding") != asdict(driver.identity):
                continue
            result = json.loads(row[8]) if row[8] is not None else None
            native = (result or {}).get("thread_id") if driver.harness == "codex" else (result or {}).get("native_session_id")
            if (row[4] in {"spawn", "resume", "replace_session"} and row[7] == "acknowledged" and native == session and result.get("binding_id") == driver.binding_id
                    and result.get("binding") == asdict(driver.identity) and result.get("ownership") == "exclusive_owned"
                    and result.get("receipt_layer") in {"runtime_acknowledged", "context_resumed"}):
                known_session = True
            if (row[4] not in {"spawn", "resume"} or body["payload"].get("profile") != driver.profile.binding()
                    or row[4] == "resume" and body["payload"].get("restore_process") is not True):
                continue
            for (raw,) in connection.execute("SELECT body FROM driver_events WHERE operation_id=? AND kind='process_started'",
                                             (row[0],)).fetchall():
                event = json.loads(raw)
                if all(event.get(name) == process[name] for name in ("pid", "birth_ref", "containment_id")):
                    process_origin = True
        if not known_session or not process_origin:
            raise DriverRejected("original Native session/process acknowledgement is unavailable")
    return process


def restoration_payload(driver, operation, session_key):
    from runtime.codex_driver import DriverRejected
    from runtime.receiver_lifecycle import AuthorizedLifecycleOperation, check_lifecycle_driver

    operation.validate(driver.clock)
    check_lifecycle_driver(operation, driver, action="resume")
    driver.check_current(operation, driver.identity)
    if operation.read_only:
        raise DriverRejected("read-only authority cannot resume a Native transport")
    previous = driver.journal.read(operation.operation_id)
    driver.check_current(operation, driver.identity)
    if previous is not None and previous["action"] == "resume" and previous["input"]["payload"].get("restore_process") is True:
        # The same operation keeps its original canonical domain after a new
        # process has become live or its ACK was lost. _run never re-enters it.
        payload = dict(previous["input"]["payload"])
        payload.pop("binding", None)
        if previous["binding_id"] != driver.binding_id or payload.get(session_key) != (getattr(driver, "thread_id", None) or driver.session_id):
            raise DriverRejected("restoration belongs to another original Native binding")
        return payload
    reference = getattr(operation, "restore_process_ref", None)
    if reference is None:
        owned = driver.owned
        poll = getattr(getattr(owned, "process", None), "poll", None)
        if callable(poll) and poll() is not None:
            raise DriverRejected("stopped Native transport requires its signed restoration identity")
        return {session_key: getattr(driver, "thread_id", None) or driver.session_id}
    if type(operation) is not AuthorizedLifecycleOperation or operation.action != "resume":
        raise DriverRejected("cold restoration requires the exact signed lifecycle operation")
    process = restoration_history(driver)
    if reference != process["evidence_ref"]:
        raise DriverRejected("restoration process identity differs from the authorized original")
    payload = {session_key: getattr(driver, "thread_id", None) or driver.session_id,
               "profile": driver.profile.binding(), "restore_process": True, "previous_process_ref": reference}
    if getattr(driver, "_lifecycle_profile_seal", None) is not None:
        payload["capacity_profile"] = dict(driver._lifecycle_profile_seal)
    return payload
