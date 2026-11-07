"""Attachment wire identity and exact committed empty-packet compatibility.

The legacy oracle executes only selected Pydantic model AST from the fixed Git
blob. It loads no historical Runtime package or task services and performs no
database, receiver, Native or network operation.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import TypeAdapter, ValidationError

from runtime.client_contracts import ClientContracts
from runtime.delivery import digest
from runtime.delivery_models import PACKET, DeliveryEnvelope, MessageAttachmentRef, MessagePacket
from runtime.delivery_node import canonical, invocation_for, logical_payload
from runtime.models import CommandEnvelope
from runtime.node import NodeJournal

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "19d7881d49ee887315c54c5bc02e0cc424061376"
CONTRACTS = ClientContracts()
CASES = [
    pytest.param({}, id="defaults"),
    pytest.param({"deadline": datetime(2026, 11, 6, 12, 30, tzinfo=UTC), "response_mode": "sync"}, id="utc"),
    pytest.param({"deadline": datetime(2026, 11, 6, 21, 30, 12, 123456, tzinfo=timezone(timedelta(hours=9))),
                  "content": "请发送原文 🧭 café", "reply_to": ("message:fixture:original",)}, id="offset-unicode"),
    pytest.param({"deadline": datetime(2026, 11, 6, 7, 15, tzinfo=timezone(-timedelta(hours=5, minutes=30))),
                  "content": 'Quoted "text" \\ slash / NUL\x00\b\f\n\r\t\x1f', "activation": "message_only"}, id="controls-negative-offset"),
]
DUMP_OPTIONS = ({}, {"exclude_none": True}, {"exclude_defaults": True}, {"exclude_unset": True},
                {"round_trip": True}, {"by_alias": True})


@pytest.fixture(scope="module")
def legacy_models():
    source = subprocess.check_output(["git", "show", BASELINE + ":runtime/delivery_models.py"], cwd=ROOT)
    blob = subprocess.check_output(["git", "rev-parse", BASELINE + ":runtime/delivery_models.py"], cwd=ROOT).decode().strip()
    assert hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest() == blob
    tree = ast.parse(source, filename=BASELINE + ":runtime/delivery_models.py")
    classes = {"DeliveryModel", "DeliveryPacket", "MessagePacket", "NoticePacket", "DeliveryEnvelope"}
    statements = []
    for item in tree.body:
        selected_import = isinstance(item, ast.ImportFrom) and item.module in {"__future__", "datetime", "typing", "pydantic"}
        selected_model = isinstance(item, ast.ClassDef) and item.name in classes
        selected_alias = isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"Packet", "PACKET"}
                                                             for target in item.targets)
        if selected_import or selected_model or selected_alias:
            statements.append(item)
    assert {node.name for node in statements if isinstance(node, ast.ClassDef)} == classes
    module = ModuleType("_acs_fixed_head_message_packet")
    module.__file__ = BASELINE + ":runtime/delivery_models.py"
    sys.modules[module.__name__] = module
    try:
        exec(compile(ast.Module(body=statements, type_ignores=[]), module.__file__, "exec"), module.__dict__)  # noqa: S102 - verified fixed Git model AST, not user input.
        assert "attachment_refs" not in module.MessagePacket.model_fields
        yield module
    finally:
        sys.modules.pop(module.__name__, None)


def packet_fields(changes=None):
    return {"project_id": "fixture", "sender": "collaborator:fixture:sender",
            "recipient": "collaborator:fixture:recipient", "content": "A natural message",
            "target_scope_id": "fixture-scope", "target_agent_slot_id": "fixture-recipient"} | (changes or {})


def envelope_fields(packet):
    return {"tenant_id": "fixture-tenant", "authority_id": "fixture-authority", "authority_incarnation": "fixture-incarnation",
            "principal_ref": "agent:fixture", "grant_ref": "grant:fixture", "message_id": "fixture-message",
            "command_id": "fixture-command", "operation_id": "fixture-operation", "endpoint_id": "fixture-endpoint",
            "binding_revision": 7, "machine_id": "fixture-machine", "node_id": "fixture-node",
            "boot_incarnation": "fixture-boot", "accepted_state_digest": "a" * 64, "packet": packet}


def command():
    return CommandEnvelope(command_id="fixture-command", command_type="message.send", idempotency_key="fixture-key",
        correlation_id="fixture-correlation", causation_id="fixture-causation", tenant_id="fixture-tenant",
        authority_id="fixture-authority", authority_incarnation="fixture-incarnation", principal_ref="agent:fixture",
        grant_ref="grant:fixture", target_kind="message", target_id="fixture-message", expected_revision=0,
        issued_at=datetime(2026, 11, 6, tzinfo=UTC), deadline=None,
        payload={"schema_version": "acs-message/1", "communication_project_id": "fixture"})


def domain_extra(packet):
    return {"packet": packet.model_dump(mode="json"), "endpoint_id": "fixture-endpoint", "binding_revision": 7}


def reference(number=1, **changes):
    return {"attachment_id": "attachment-" + f"{number:032x}", "name": "草稿 \"safe\".txt",
            "media_type": "application/octet-stream", "bytes": 4, "sha256": hashlib.sha256(b"data").hexdigest()} | changes


@pytest.mark.parametrize("changes", CASES)
@pytest.mark.parametrize("empty", [None, (), []], ids=["omitted", "tuple", "json-array"])
def test_empty_attachment_field_preserves_exact_head_packet_envelope_and_adapter_bytes(legacy_models, changes, empty):
    inputs = packet_fields(changes)
    old = legacy_models.MessagePacket(**inputs)
    current = MessagePacket(**inputs, **({} if empty is None else {"attachment_refs": empty}))
    old_envelope = legacy_models.DeliveryEnvelope(**envelope_fields(old))
    current_envelope = DeliveryEnvelope(**envelope_fields(current))
    assert current.schema_version == old.schema_version == "acs-message/1"
    for options in DUMP_OPTIONS:
        assert current.model_dump(**options) == old.model_dump(**options)
        assert current.model_dump(mode="json", **options) == old.model_dump(mode="json", **options)
        for indent in (None, 2):
            assert current.model_dump_json(indent=indent, **options) == old.model_dump_json(indent=indent, **options)
            assert current_envelope.model_dump_json(indent=indent, **options) == old_envelope.model_dump_json(indent=indent, **options)
        assert current_envelope.model_dump(mode="json", **options) == old_envelope.model_dump(mode="json", **options)
    assert PACKET.dump_json(current) == legacy_models.PACKET.dump_json(old)
    assert TypeAdapter(DeliveryEnvelope).dump_json(current_envelope) == TypeAdapter(legacy_models.DeliveryEnvelope).dump_json(old_envelope)
    assert legacy_models.PACKET.validate_json(current.model_dump_json(), strict=True).model_dump_json() == old.model_dump_json()
    assert PACKET.validate_json(old.model_dump_json(), strict=True).model_dump_json() == current.model_dump_json()
    assert legacy_models.DeliveryEnvelope.model_validate_json(current_envelope.model_dump_json(), strict=True).model_dump_json() == old_envelope.model_dump_json()


@pytest.mark.parametrize("changes", CASES)
def test_empty_packet_retains_legacy_logical_payload_and_all_existing_hash_boundaries(legacy_models, changes):
    old_packet = legacy_models.MessagePacket(**packet_fields(changes))
    current_packet = MessagePacket(**packet_fields(changes), attachment_refs=[])
    old_envelope = legacy_models.DeliveryEnvelope(**envelope_fields(old_packet))
    current_envelope = DeliveryEnvelope(**envelope_fields(current_packet))
    # This helper is deliberately independent of the current logical_payload:
    # its exact definition is compiled from the same fixed committed source.
    source = subprocess.check_output(["git", "show", BASELINE + ":runtime/delivery_node.py"], cwd=ROOT)
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "logical_payload")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), BASELINE + ":logical_payload", "exec"), namespace)  # noqa: S102 - exact fixed Git helper AST, not a historical Runtime import.
    old_logical = namespace["logical_payload"](old_envelope)
    current_logical = logical_payload(current_envelope)
    assert canonical(current_logical).encode() == canonical(old_logical).encode()
    assert NodeJournal.payload_digest(current_logical) == NodeJournal.payload_digest(old_logical)
    assert command().canonical_input(domain_extra(current_packet)) == command().canonical_input(domain_extra(old_packet))
    assert command().canonical_hash(domain_extra(current_packet)) == command().canonical_hash(domain_extra(old_packet))
    assert digest(current_envelope.model_dump(mode="json")) == digest(old_envelope.model_dump(mode="json"))
    invocation = invocation_for(current_envelope, "fixture-attempt")
    assert invocation.envelope_digest == hashlib.sha256(canonical(old_envelope.model_dump(mode="json")).encode()).hexdigest()
    assert invocation.logical_payload_digest == NodeJournal.payload_digest(old_logical)


def test_frozen_wire_reference_matches_client_metadata_shape_and_is_not_a_download_capability():
    supplied = reference()
    frozen = MessageAttachmentRef(**supplied)
    assert frozen.model_dump(mode="json") == CONTRACTS.validate("AttachmentRef", supplied)
    assert set(MessageAttachmentRef.model_fields) == set(CONTRACTS.schema("AttachmentRef")["$defs"]["AttachmentRef"]["properties"])
    packet = MessagePacket(**packet_fields(), attachment_refs=[supplied])
    supplied["name"] = "caller changed its own dictionary"
    assert packet.attachment_refs[0].name == frozen.name
    with pytest.raises(ValidationError):
        packet.attachment_refs[0].bytes = 9


def identities(refs):
    packet = MessagePacket(**packet_fields(), attachment_refs=refs)
    envelope = DeliveryEnvelope(**envelope_fields(packet))
    invocation = invocation_for(envelope, "fixture-attempt")
    return (packet.model_dump_json(), envelope.model_dump_json(), canonical(logical_payload(envelope)),
            command().canonical_hash(domain_extra(packet)), invocation.envelope_digest, invocation.logical_payload_digest)


@pytest.mark.parametrize("field,value", [
    ("attachment_id", "attachment-" + "c" * 32), ("name", "different display name"),
    ("media_type", "text/plain"), ("bytes", 5), ("sha256", "b" * 64),
])
def test_each_frozen_reference_field_changes_packet_envelope_logical_and_canonical_identity(field, value):
    first, changed = reference(), reference(**{field: value})
    assert all(left != right for left, right in zip(identities([first]), identities([changed]), strict=True))


def test_reference_order_is_preserved_and_covered_by_all_identity_boundaries(legacy_models):
    refs = [reference(1), reference(2, name="second.txt")]
    packet = MessagePacket(**packet_fields(), attachment_refs=refs)
    assert packet.model_dump(mode="json")["attachment_refs"] == refs
    assert [item.attachment_id for item in PACKET.validate_json(packet.model_dump_json(), strict=True).attachment_refs] == [item["attachment_id"] for item in refs]
    assert all(left != right for left, right in zip(identities(refs), identities(list(reversed(refs))), strict=True))
    # An old receiver must refuse the extension, rather than silently discard it.
    with pytest.raises(ValidationError):
        legacy_models.PACKET.validate_json(packet.model_dump_json(), strict=True)


@pytest.mark.parametrize("change", [
    {"attachment_id": "https://example.test/bytes"}, {"attachment_id": "attachment-" + "A" * 32},
    {"attachment_id": "attachment-short"}, {"name": ""}, {"name": "x" * 256},
    {"media_type": ""}, {"media_type": "x" * 257}, {"bytes": 0}, {"bytes": -1},
    {"bytes": True}, {"bytes": "4"}, {"bytes": 4.0}, {"sha256": "A" * 64}, {"sha256": "abc"},
    {"url": "http://127.0.0.1/private"}, {"path": "../../secret"}, {"upload_path": "/private/stage"},
], ids=["url-id", "upper-id", "short-id", "empty-name", "long-name", "empty-type", "long-type",
        "zero-bytes", "negative-bytes", "bool-bytes", "string-bytes", "float-bytes", "upper-digest",
        "short-digest", "extra-url", "extra-path", "extra-upload-path"])
def test_malformed_or_path_bearing_references_are_refused(change):
    with pytest.raises(ValidationError):
        MessagePacket(**packet_fields(), attachment_refs=[reference() | change])


def test_duplicate_attachment_identity_and_excess_count_are_refused():
    with pytest.raises(ValidationError):
        MessagePacket(**packet_fields(), attachment_refs=[reference(), reference(name="same identity different metadata")])
    with pytest.raises(ValidationError):
        MessagePacket(**packet_fields(), attachment_refs=[reference(number) for number in range(9)])
    accepted = MessagePacket(**packet_fields(), attachment_refs=[reference(number) for number in range(8)])
    assert len(PACKET.validate_json(accepted.model_dump_json(), strict=True).attachment_refs) == 8


def test_wire_revalidation_cannot_trust_model_copy_or_construct_bypasses():
    valid = MessagePacket(**packet_fields(), attachment_refs=[reference()])
    forged = valid.model_copy(update={"attachment_refs": (valid.attachment_refs[0].model_copy(update={"bytes": -1}),)})
    with pytest.raises(ValidationError):
        PACKET.validate_json(forged.model_dump_json(), strict=True)
    body = json.loads(valid.model_dump_json())
    body["attachment_refs"][0]["url"] = "http://127.0.0.1/private"
    with pytest.raises(ValidationError):
        PACKET.validate_json(json.dumps(body), strict=True)
    # Copy mutation does not mutate either the original Packet or caller metadata.
    assert deepcopy(valid.model_dump(mode="json"))["attachment_refs"] == [reference()]
