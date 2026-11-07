"""Read-only Native input evidence; readiness is not authorization to submit.

The returned ``axes`` contain only classifications, never prompt/transcript or
pending-request bodies. Every unknown axis has value None. Positive absence of
blockers requires a dedicated owned API receiver and validated current protocol
responses. Attached sessions cannot establish dedicated input ownership.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

from runtime.codex_driver import CodexAppServerDriver
from runtime.opencode_driver import OpenCodeNativeDriver

MAX_SCHEMA_BYTES = 16 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
MAX_PENDING_BYTES = 256 * 1024
MAX_PENDING = 128
AXES = ("connection", "process", "session", "input", "blocker")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _read_json(path, maximum):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("schema exceeds bound")
    return raw, json.loads(raw)


def _bounded(value, maximum):
    # Bound both traversal and encoded size before invoking a schema validator.
    queue = [(value, 0)]
    count = 0
    while queue:
        current, depth = queue.pop()
        count += 1
        if count > (200000 if maximum == MAX_SCHEMA_BYTES else 20000) or depth > 32:
            raise ValueError("Native response complexity exceeds bound")
        if isinstance(current, dict):
            if any(not isinstance(key, str) for key in current):
                raise ValueError("Native JSON keys must be strings")
            queue.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            queue.extend((item, depth + 1) for item in current)
    if len(json.dumps(value, allow_nan=False).encode()) > maximum:
        raise ValueError("Native response exceeds bound")


def _schema(document, selected):
    """Expand only local references; no schema can trigger a remote retrieval."""
    remaining = [20000]

    def expand(item, ancestors=(), depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 64:
            raise ValueError("schema complexity exceeds bound")
        if isinstance(item, list):
            return [expand(child, ancestors, depth + 1) for child in item]
        if not isinstance(item, dict):
            return item
        if any(key.startswith("$") and key.lower().endswith("ref") and key != "$ref" for key in item):
            raise ValueError("dynamic or recursive Native schema resolution is unsupported")
        if "$ref" in item:
            reference = item["$ref"]
            if not isinstance(reference, str) or not reference.startswith("#/") or reference in ancestors:
                raise ValueError("only acyclic local Native schema references are supported")
            target = document
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            referred = expand(target, (*ancestors, reference), depth + 1)
            siblings = {key: value for key, value in item.items() if key != "$ref"}
            return {"allOf": [referred, expand(siblings, ancestors, depth + 1)]} if siblings else referred
        return {key: expand(value, ancestors, depth + 1) for key, value in item.items()}

    expanded = expand(selected)
    Draft202012Validator.check_schema(expanded)
    return Draft202012Validator(expanded)


def _response_schema(document, path):
    endpoint = document["paths"][path]
    if not isinstance(endpoint, dict) or "get" not in endpoint:
        raise ValueError("Native protocol does not expose a read-only pending inventory")
    expected = {"/permission": "permission.list", "/question": "question.list", "/session/status": "session.status"}
    if endpoint["get"].get("operationId") != expected[path]:
        raise ValueError("Native read method has an unrecognized protocol identity")
    return _schema(document, endpoint["get"]["responses"]["200"]["content"]["application/json"]["schema"])


def _codex_status_schema(document):
    for container in (document.get("definitions", {}).get("v2", {}), document.get("definitions", {}),
                      document.get("$defs", {})):
        if "ThreadStatus" in container and "ThreadActiveFlag" in container:
            flag = container["ThreadActiveFlag"]
            if not {"waitingOnApproval", "waitingOnUserInput"} <= set(flag.get("enum", [])):
                raise ValueError("Native schema does not prove pending-input flags")
            return _schema(document, container["ThreadStatus"])
    raise ValueError("Native thread status schema is unavailable")


def _pending(driver, operation, path, validator, session):
    status, items = driver._http(operation, "GET", path, max_bytes=MAX_PENDING_BYTES)
    if status != 200 or not isinstance(items, list) or len(items) > MAX_PENDING:
        raise ValueError("pending Native requests are unavailable or outside bound")
    _bounded(items, MAX_PENDING_BYTES)
    validator.validate(items)
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("pending Native request identities are duplicated")
    return any(item["sessionID"] == session for item in items)


def observe_native_input(driver, operation):
    """Return classification-only evidence for a bound Codex/OpenCode Driver.

    Shape: binding_id, native_session_ref, ownership, dedicated_input,
    observed_at/expires_at, source/evidence_ref, protocol_digest/config_digest,
    schema_verified and axes[axis]={knowledge,value,reason_code,evidence_ref}.
    Positive state remains separate from the final Native admission fence.
    """
    axes = {axis: {"knowledge": "unknown", "value": None, "reason_code": "not_observed",
                   "evidence_ref": None} for axis in AXES}
    result = {"binding_id": None, "native_session_ref": None, "ownership": "unknown",
        "dedicated_input": False, "observed_at": None, "expires_at": None, "source": "native_api",
        "evidence_ref": None, "protocol_digest": None, "config_digest": None,
        "schema_verified": False, "axes": axes}
    if not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver)):
        return result

    def known(axis, value):
        axes[axis].update(knowledge="observed", value=value, reason_code=None)

    def stamp():
        value = driver.clock.observation_time() if driver.clock is not None else datetime.now(UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation clock is unavailable")
        result["observed_at"] = value.isoformat()
        result["expires_at"] = (value + timedelta(seconds=2)).isoformat()

    with driver._lock:
        try:
            operation.validate(driver.clock)
            driver.check_current(operation, driver.identity)
            before = (driver.binding_id, asdict(driver.identity), driver.ownership,
                      getattr(driver, "thread_id", None), driver.session_id, id(driver.owned))
            session = driver.thread_id if isinstance(driver, CodexAppServerDriver) else driver.session_id
            result.update(binding_id=driver.binding_id, ownership=driver.ownership)
            stamp()
            proof = None
            if driver.owned is not None and driver.supervisor is not None:
                proof = driver.supervisor.inspect(driver.owned)
            process_present = (isinstance(proof, dict) and proof.get("verified") is True
                and proof.get("root_exited") is False and proof.get("birth_ref") == driver.owned.birth_ref
                and proof.get("containment_id") == driver.owned.containment_id)
            if process_present:
                known("process", "present")
            elif isinstance(proof, dict) and proof.get("verified") is True and proof.get("root_exited") is True:
                known("process", "absent")
            dedicated = driver.ownership == "exclusive_owned" and process_present
            result["dedicated_input"] = dedicated

            if isinstance(driver, CodexAppServerDriver):
                raw, document = _read_json(driver.profile.schema_path, MAX_SCHEMA_BYTES)
                result["protocol_digest"] = hashlib.sha256(raw).hexdigest()
                config = Path(driver.profile.codex_home) / "config.toml"
                with config.open("rb") as stream:
                    config_bytes = stream.read(MAX_CONFIG_BYTES + 1)
                if len(config_bytes) > MAX_CONFIG_BYTES:
                    raise ValueError("Native configuration exceeds bound")
                result["config_digest"] = hashlib.sha256(config_bytes).hexdigest()
                if (result["protocol_digest"] != driver.profile.schema_sha256
                        or result["config_digest"] != driver.profile.config_sha256):
                    raise ValueError("Native generated schema or configuration changed")
                validator = _codex_status_schema(document)
                result["schema_verified"] = True
                view = driver.inspect_readiness(operation, before_status=stamp)
                thread = view["thread"]
                if thread.get("id") != session or thread.get("sessionId") != driver.session_id:
                    raise ValueError("Native session identity changed")
                status = thread["status"]
                _bounded(status, 16384)
                validator.validate(status)
                state = status.get("type")
                expected = {"type", "activeFlags"} if state == "active" else {"type"}
                if set(status) != expected or state not in {"idle", "active", "notLoaded", "systemError"}:
                    raise ValueError("unrecognized Native status fields")
                flags = status.get("activeFlags", [])
                if (not isinstance(flags, list) or len(flags) > 2 or len(set(flags)) != len(flags)
                        or set(flags) - {"waitingOnApproval", "waitingOnUserInput"}):
                    raise ValueError("unrecognized Native blocker flag")
                known("connection", "connected")
                if state in {"idle", "active"}:
                    known("session", "present")
                    known("input", "ready" if state == "idle" else "busy")
                    if dedicated:
                        known("blocker", "approval" if "waitingOnApproval" in flags else
                            "question" if "waitingOnUserInput" in flags else "none")
            else:
                code, document = driver._http(operation, "GET", "/doc", max_bytes=MAX_SCHEMA_BYTES)
                if code != 200 or not isinstance(document, dict):
                    raise ValueError("Native protocol schema unavailable")
                _bounded(document, MAX_SCHEMA_BYTES)
                result["protocol_digest"] = _digest(document)
                if driver.profile.execution_mode == "restricted":
                    raw, pinned = _read_json(driver.profile.schema_path, MAX_SCHEMA_BYTES)
                    if (hashlib.sha256(raw).hexdigest() != driver.profile.schema_sha256
                            or _digest(pinned) != result["protocol_digest"]):
                        raise ValueError("Native protocol differs from the pinned schema")
                permission_schema = _response_schema(document, "/permission")
                question_schema = _response_schema(document, "/question")
                status_schema = _response_schema(document, "/session/status")
                code, config = driver._http(operation, "GET", "/config", max_bytes=MAX_CONFIG_BYTES)
                if code != 200 or not isinstance(config, dict):
                    raise ValueError("Native configuration unavailable")
                _bounded(config, MAX_CONFIG_BYTES)
                result["config_digest"] = _digest(config)
                result["schema_verified"] = True
                view = driver.inspect_readiness(operation, before_status=stamp)
                if view["session"].get("id") != session:
                    raise ValueError("Native session identity changed")
                # The existing Driver's status helper defaults omitted sessions
                # to idle. This proof requires an explicit current inventory row.
                code, statuses = driver._http(operation, "GET", "/session/status", max_bytes=MAX_PENDING_BYTES)
                _bounded(statuses, MAX_PENDING_BYTES)
                status_schema.validate(statuses)
                if code != 200 or not isinstance(statuses, dict) or session not in statuses:
                    raise ValueError("Native status inventory does not contain this session")
                status = statuses[session]
                waiting_approval = _pending(driver, operation, "/permission", permission_schema, session)
                waiting_question = _pending(driver, operation, "/question", question_schema, session)
                known("connection", "connected")
                known("session", "present")
                known("input", "ready" if status["type"] == "idle" else "busy")
                if dedicated:
                    known("blocker", "approval" if waiting_approval else "question" if waiting_question else "none")
            after = (driver.binding_id, asdict(driver.identity), driver.ownership,
                     getattr(driver, "thread_id", None), driver.session_id, id(driver.owned))
            operation.validate(driver.clock)
            driver.check_current(operation, driver.identity)
            if before != after:
                raise ValueError("Native receiving generation changed during observation")
            if dedicated:
                current_proof = driver.supervisor.inspect(driver.owned)
                if (not isinstance(current_proof, dict) or current_proof.get("verified") is not True
                        or current_proof.get("root_exited") is not False
                        or current_proof.get("birth_ref") != driver.owned.birth_ref
                        or current_proof.get("containment_id") != driver.owned.containment_id):
                    raise ValueError("Native process identity or liveness changed during observation")
            now = driver.clock.observation_time() if driver.clock is not None else datetime.now(UTC)
            if (now >= datetime.fromisoformat(result["expires_at"])
                    or now < datetime.fromisoformat(result["observed_at"])):
                raise ValueError("Native evidence expired during observation")
            if axes["session"]["value"] == "present":
                result["native_session_ref"] = session
            if not dedicated:
                axes["blocker"]["reason_code"] = "native_input_ownership_unverified"
            result["evidence_ref"] = "native-input-observation:" + _digest({
                "binding": before, "protocol": result["protocol_digest"], "config": result["config_digest"],
                "observed_at": result["observed_at"], "axes": axes})
            for observation in axes.values():
                if observation["knowledge"] == "observed":
                    observation["evidence_ref"] = result["evidence_ref"]
        except Exception:  # noqa: BLE001 - unavailable evidence never permits input.
            for axis in AXES:
                axes[axis].update(knowledge="unknown", value=None, reason_code="native_evidence_unavailable", evidence_ref=None)
            result.update(native_session_ref=None, dedicated_input=False, schema_verified=False)
    return result
