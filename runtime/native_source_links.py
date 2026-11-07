"""Exact original-message provenance from an already existing Driver journal.

This unmounted, refs-only port grants no Core or Host authority. Its server
composition must supply an existing verified Core reader, the original trusted
provider registration and a configured DriverJournal locator. It never opens a
caller path, reads a transcript, reconciles, contacts a Host or submits input.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from runtime.codex_driver import DriverJournal
from runtime.codex_driver import digest as journal_digest
from runtime.delivery_models import InvocationRequest
from runtime.delivery_node import invocation_for
from runtime.native_view_models import ProviderAdmission
from runtime.receiver_contract import NativeHandoffContext, native_generation

MAX_RECORD_BYTES, MAX_EVENTS = 2 * 1024 * 1024, 1024
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class NativeSourceSession:
    provider_ref: str
    session_ref: str
    host_ref: str
    generation: str
    authority: str

    def as_client(self):
        return {"providerRef": self.provider_ref, "sessionRef": self.session_ref, "hostRef": self.host_ref,
                "generation": self.generation, "authority": self.authority}


@dataclass(frozen=True, slots=True)
class NativeSourceLink:
    message_handle: str
    operation_id: str
    binding_epoch: int
    native_session: NativeSourceSession
    native_input_ref: str | None = None
    native_turn_ref: str | None = None

    def as_client(self):
        value = {"messageHandle": self.message_handle, "operationId": self.operation_id,
                 "bindingEpoch": self.binding_epoch, "nativeSession": self.native_session.as_client()}
        if self.native_input_ref is not None:
            value["nativeInputRef"] = self.native_input_ref
        if self.native_turn_ref is not None:
            value["nativeTurnRef"] = self.native_turn_ref
        return value


@dataclass(frozen=True, slots=True)
class NativeSourceLinkResult:
    value: NativeSourceLink | None
    reason_code: str | None
    evidence_ref: str | None = None

    @property
    def available(self):
        return self.value is not None


class _Unavailable(ValueError):
    pass


def _require(condition, reason="native_source_uncorrelated"):
    if not condition:
        raise _Unavailable(reason)


def _reference(value):
    return (type(value) is str and bool(value.strip()) and len(value) <= 512
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _read(journal, operation_id):
    """One readonly SQLite snapshot; extract protocol identities, never transcript bodies."""
    _require(isinstance(journal, DriverJournal), "native_source_locator_unavailable")
    path = Path(journal.path).absolute()
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not path.is_symlink()
        and not getattr(before, "st_file_attributes", 0) & 0x400, "native_source_locator_unavailable")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("BEGIN")
        row = connection.execute("SELECT binding_id,action,input_hash,input_json,state,result_json "
                                 "FROM driver_operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise _Unavailable("native_source_operation_missing")
        _require(len(row[3].encode()) <= MAX_RECORD_BYTES and row[5] is not None
                 and len(row[5].encode()) <= 65536, "native_source_record_unavailable")
        # Native thread/read result bodies and native_event tool/transcript data
        # are intentionally not selected. Only protocol correlation fields leave SQLite.
        fields = ("request_id", "method", "path", "status", "body_digest", "binding", "command_id", "message_id",
                  "params.threadId", "params.clientUserMessageId", "params.input[0].text", "params.input[0].type",
                  "result.turn.id")
        expressions = ",".join("json_extract(body,'$." + field + "')" for field in fields)
        expressions += ",json_array_length(body,'$.params.input')"
        rows = connection.execute("SELECT sequence,kind," + expressions + " FROM driver_events WHERE operation_id=? "
            "AND kind IN ('rpc_intent','rpc_dispatch','rpc_response','http_intent','http_dispatch','http_response') "
            "ORDER BY sequence LIMIT ?", (operation_id, MAX_EVENTS + 1)).fetchall()
        _require(len(rows) <= MAX_EVENTS, "native_source_evidence_budget")
        events = [dict(zip(("sequence", "kind", *fields, "params.input_count"), item, strict=True)) for item in rows]
        after = path.lstat()
        _require((before.st_dev, before.st_ino, getattr(before, "st_birthtime_ns", None)) ==
                 (after.st_dev, after.st_ino, getattr(after, "st_birthtime_ns", None))
                 and not path.is_symlink() and not getattr(after, "st_file_attributes", 0) & 0x400,
                 "native_source_locator_changed")
        return {"binding_id": row[0], "action": row[1], "input_hash": row[2], "input": json.loads(row[3]),
                "state": row[4], "result": json.loads(row[5])}, events
    finally:
        connection.close()


def _protocol(record, events, context, invocation):
    payload, receipt = record["input"]["payload"], record["result"]
    if "thread_id" in payload:
        turn = receipt.get("turn_id")
        _require(_reference(turn) and receipt.get("thread_id") == payload["thread_id"] == context.native_session_ref)
        intents = [event for event in events if event["kind"] == "rpc_intent" and event["method"] == "turn/start"]
        dispatched = [event for event in events if event["kind"] == "rpc_dispatch" and event["method"] == "turn/start"]
        _require(len(dispatched) == 1, "native_source_dispatch_ambiguous")
        dispatch = dispatched[0]
        matching = [event for event in intents if event["request_id"] == dispatch["request_id"]]
        _require(len(matching) == 1)
        intent = matching[0]
        responses = [event for event in events if event["kind"] == "rpc_response"
                     and event["request_id"] == intent["request_id"] and event["result.turn.id"] == turn]
        _require(len(responses) == 1 and intent["sequence"] < dispatch["sequence"] < responses[0]["sequence"])
        _require(intent["params.threadId"] == context.native_session_ref
                 and intent["params.clientUserMessageId"] == invocation.message_id
                 and intent["params.input[0].type"] == "text"
                 and intent["params.input_count"] == 1
                 and intent["params.input[0].text"] == payload["text"]
                 and intent["command_id"] == invocation.command_id and intent["message_id"] == invocation.message_id)
        for event in (intent, dispatch):
            _require(json.loads(event["binding"]) == payload["binding"])
        # clientUserMessageId was supplied by Core, not a Host-created input id.
        return None, turn
    native_id = receipt.get("native_message_id")
    _require(_reference(native_id) and receipt.get("native_session_id") == payload.get("native_session_id") == context.native_session_ref
             and payload.get("native_message_id") == native_id
             and receipt.get("native_ack_type") == "exact_message_readback")
    post = "/session/" + context.native_session_ref + "/prompt_async"
    readback = "/session/" + context.native_session_ref + "/message/" + native_id
    intents = [e for e in events if e["kind"] == "http_intent" and e["method"] == "POST" and e["path"] == post]
    dispatched = [e for e in events if e["kind"] == "http_dispatch" and e["method"] == "POST" and e["path"] == post]
    responses = [e for e in events if e["kind"] == "http_response" and e["method"] == "POST" and e["path"] == post and e["status"] == 204]
    reads = [e for e in events if e["kind"] == "http_response" and e["method"] == "GET" and e["path"] == readback
             and type(e["status"]) is int and 200 <= e["status"] < 300 and type(e["body_digest"]) is str
             and _DIGEST.fullmatch(e["body_digest"])]
    _require(len(dispatched) == 1 and len(intents) == 1 and len(responses) == 1 and reads
             and intents[0]["sequence"] < dispatched[0]["sequence"] < responses[0]["sequence"]
             and any(e["sequence"] > responses[0]["sequence"] for e in reads), "native_source_exact_readback_missing")
    _require(intents[0]["body_digest"] == dispatched[0]["body_digest"]
             and all(json.loads(event["binding"]) == payload["binding"] for event in (intents[0], dispatched[0])))
    read_intents = [e["sequence"] for e in events if e["kind"] == "http_intent" and e["method"] == "GET" and e["path"] == readback]
    first_intent = min(read_intents, default=float("inf"))
    read_dispatches = [e["sequence"] for e in events if e["kind"] == "http_dispatch" and e["method"] == "GET"
                       and e["path"] == readback and e["sequence"] > first_intent]
    first_dispatch = min(read_dispatches, default=float("inf"))
    _require(any(e["sequence"] > first_dispatch for e in reads), "native_source_exact_readback_missing")
    return native_id, None


def _project(invocation, provider, record, events):
    _require(type(provider) is ProviderAdmission, "native_source_provider_unavailable")
    provider = ProviderAdmission.model_validate_json(provider.model_dump_json())
    packet, envelope = invocation.envelope.packet, invocation.envelope
    _require(packet.schema_version == "acs-message/1" and packet.activation == "invoke", "native_source_not_requested")
    expected = invocation_for(envelope, invocation.attempt_id)
    _require(all(getattr(invocation, field) == getattr(expected, field) for field in (
        "invocation_id", "dispatch_id", "runtime_dispatched_receipt_id", "operation_id", "message_id", "command_id",
        "envelope_digest", "logical_payload_digest", "selection_digest", "accepted_state_digest")), "native_source_core_lineage_changed")
    _require(record["state"] == "acknowledged" and record["action"] == "invoke"
             and journal_digest(record["input"]) == record["input_hash"], "native_source_ack_missing")
    body, receipt = record["input"], record["result"]
    context = NativeHandoffContext.model_validate_json(json.dumps(body["payload"].get("handoff_context")))
    binding = body["payload"]["binding"]
    message_handle = f"message:{packet.project_id}:{invocation.message_id}"
    _require((context.operation_id, context.command_id, context.message_id, context.message_handle, context.receiver_id,
              context.actor_address, context.authority_id, context.authority_incarnation, context.binding_epoch,
              context.canonical_hash, context.selection_digest) ==
             (invocation.invocation_id, invocation.command_id, invocation.message_id, message_handle, envelope.endpoint_id,
              packet.recipient, envelope.authority_id, envelope.authority_incarnation, envelope.binding_revision,
              invocation.envelope_digest, invocation.selection_digest))
    _require(body["binding_id"] == record["binding_id"] == context.driver_binding_id
             and body["command_id"] == invocation.command_id and body["message_id"] == invocation.message_id
             and body["action"] == "invoke" and receipt.get("receipt_layer") == "runtime_acknowledged"
             and receipt.get("operation_id") == invocation.invocation_id
             and receipt.get("command_id") == invocation.command_id and receipt.get("message_id") == invocation.message_id
             and receipt.get("binding_id") == context.driver_binding_id and receipt.get("binding") == binding)
    _require(context.input_digest == hashlib.sha256(body["payload"]["text"].encode()).hexdigest()
             and context.provider_generation == native_generation(context.driver_binding_id, binding, context.native_session_ref))
    auth = {"grant_ref": body["grant_ref"], "authority_id": envelope.authority_id,
            "authority_incarnation": envelope.authority_incarnation, "binding_revision": binding["revision"],
            "accepted_state_digest": invocation.accepted_state_digest}
    _require(context.auth_revision == hashlib.sha256(json.dumps(auth, sort_keys=True).encode()).hexdigest())
    selection, selected = provider.selection, provider.selection.binding
    _require((selection.tenant_id, selection.project_id, selection.scope_id, selection.agent_slot_id, selection.node_id,
              selection.boot_incarnation, selected.receiver_id, selected.actor_address, selected.binding_epoch,
              selected.authority_id, selected.authority_incarnation, selected.execution_host_ref) ==
             (envelope.tenant_id, packet.project_id, packet.target_scope_id, packet.target_agent_slot_id, envelope.node_id,
              envelope.boot_incarnation, envelope.endpoint_id, packet.recipient, envelope.binding_revision,
              envelope.authority_id, envelope.authority_incarnation, envelope.machine_id), "native_source_provider_selection_changed")
    _require(binding["node_id"] == envelope.node_id and binding["node_boot_id"] == envelope.boot_incarnation
             and binding["agent_slot_id"] == packet.target_agent_slot_id)
    _require((selection.runtime_id is None or selection.runtime_id == binding["runtime_id"])
             and (selection.runtime_binding_revision is None or selection.runtime_binding_revision == binding["revision"])
             and (selected.native_session_ref is None or selected.native_session_ref == context.native_session_ref)
             and (selected.provider_generation is None or selected.provider_generation == context.provider_generation)
             and provider.native_authority in {"orca", "harness"}, "native_source_provider_selection_changed")
    _require(all(_reference(value) for value in (provider.provider_ref, context.native_session_ref,
             envelope.machine_id, context.provider_generation)), "native_source_provider_selection_changed")
    native_input, native_turn = _protocol(record, events, context, invocation)
    link = NativeSourceLink(message_handle, invocation.operation_id, context.binding_epoch,
        NativeSourceSession(provider.provider_ref, context.native_session_ref, envelope.machine_id,
                            context.provider_generation, provider.native_authority), native_input, native_turn)
    proof = "driver-source:" + journal_digest([invocation.invocation_id, record["input_hash"], journal_digest(receipt)])
    return NativeSourceLinkResult(link, None, proof)


class NativeSourceLinkPort:
    """Server-configured local provenance reader; public entry accepts references only.

    read_original MUST use the existing authenticated/verified Core source for
    the actual original message/operation/attempt. Provider and journal locators
    MUST be trusted original-registration composition, never request models,
    filesystem paths, current NativeLink values or provider-brand guesses.
    authorize_original(invocation) must return None or raise on the current
    reader's original message/operation/Scope ACL; it grants no Host permission.
    No remote transport is supplied: an unavailable locator remains unavailable.
    """

    def __init__(self, *, read_original: Callable, original_provider: Callable, journal_for: Callable,
                 authorize_original: Callable):
        if not all(callable(port) for port in (read_original, original_provider, journal_for, authorize_original)):
            raise TypeError("explicit original Core/provider/journal/authorization ports are required")
        self._core, self._provider, self._journal, self._authorize = read_original, original_provider, journal_for, authorize_original

    def _check(self, invocation):
        if self._authorize(invocation) is not None:
            raise PermissionError("Native source authorization requires an explicit current Core check")

    def read(self, message_handle, operation_id):
        if not _reference(message_handle) or not _reference(operation_id):
            raise ValueError("bounded original message and operation references are required")
        invocation = self._core(message_handle, operation_id)
        if type(invocation) is not InvocationRequest:
            return NativeSourceLinkResult(None, "native_source_core_unavailable")
        try:
            invocation = InvocationRequest.model_validate_json(invocation.model_dump_json())
        except (TypeError, ValueError):
            return NativeSourceLinkResult(None, "native_source_core_unavailable")
        expected = f"message:{invocation.envelope.packet.project_id}:{invocation.message_id}"
        if (message_handle, operation_id) != (expected, invocation.operation_id):
            return NativeSourceLinkResult(None, "native_source_core_lineage_changed")
        self._check(invocation)
        try:
            if invocation.envelope.packet.schema_version != "acs-message/1" or invocation.envelope.packet.activation != "invoke":
                return NativeSourceLinkResult(None, "native_source_not_requested")
            record, events = _read(self._journal(invocation), invocation.invocation_id)
            return _project(invocation, self._provider(invocation), record, events)
        except _Unavailable as error:
            return NativeSourceLinkResult(None, str(error))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
            return NativeSourceLinkResult(None, "native_source_evidence_unavailable")
        finally:
            self._check(invocation)
