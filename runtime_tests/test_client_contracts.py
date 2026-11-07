"""Static Client 1 contract/evidence tests; all values are synthetic fixtures."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from runtime.client_contracts import (
    ClientContracts,
    ClientContractSourceError,
    ClientContractViolation,
    _safe_document,
)
from runtime.receiver_contract import NativeAdmissionResult
from tools.runtime.export_client_contracts import document, typescript

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "ec5432feba0d47d207ad59261c36324f92a95e478f4c858d2fc9264bdeb6f3a8"
CONTRACTS = ClientContracts()


def delivery():
    return {"message_handle": "message:synthetic:request", "accepted_by_authority": True,
        "target_inbox_committed": True,
        "native": {"state": "unknown", "operation_ref": "operation:synthetic", "binding_epoch": 1,
            "provider_generation": "generation:synthetic", "evidence_ref": None,
            "native_input_ref": None, "reason_code": "ack_unconfirmed"},
        "consumption": {"state": "unobservable", "semantics": "provider_input_consumed", "evidence_ref": None},
        "response": {"present": True, "message_handle": "message:synthetic:reply"}, "revision": 1}


def message():
    text = "请核对接口。"
    return {"message_handle": "message:synthetic:request", "project_id": "synthetic",
        "conversation_id": "conversation:synthetic", "sender": "collaborator:synthetic:a",
        "to": "collaborator:synthetic:b", "content": {"text": text, "offset": 0,
            "next_offset": None, "total_bytes": len(text.encode()), "digest": hashlib.sha256(text.encode()).hexdigest()},
        "reply_to": [], "attachment_refs": [], "conversation_sequence": "1",
        "committed_at": "2026-11-06T02:00:00Z", "revision": 1, "source": "acs_agent", "first_reply_handle": None}


def test_packaged_contract_is_fixed_and_sdk_reproducible():
    path = ROOT / "runtime/client_models.schema.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    upstream = deepcopy(original)
    upstream["$defs"]["Draft"]["properties"]["updated_at"] = {"type": "string", "format": "date-time"}
    del upstream["$defs"]["Draft"]["allOf"]
    upstream["$defs"]["Notice"]["properties"]["created_at"] = {"type": "string", "format": "date-time"}
    limits = upstream["$defs"]["Meta"]["properties"]["limits"]
    for field in ("attachment_total_bytes", "attachment_staging_bytes", "attachment_project_staging_bytes", "attachment_staging_seconds",
                  "native_link_count", "native_link_history_revisions", "native_link_write_receipts", "native_link_metadata_bytes"):
        del limits["properties"][field]
        limits["required"].remove(field)
    for model, fields in (("NativeLink", ("host_ref", "provider_generation")),
                          ("NativeLinkWrite", ("expected_host_ref", "expected_provider_generation"))):
        for field in fields:
            del upstream["$defs"][model]["properties"][field]
            upstream["$defs"][model]["required"].remove(field)
    # The optional provenance read extension preserves the original pack's
    # unextended contract. Keep its original hash rather than rewriting it.
    del upstream["$defs"]["ReadMessageResponse"]["properties"]["native_source"]
    for model in ("NativeSourceSession", "SourceLink", "NativeSourceLookup"):
        del upstream["$defs"][model]
    assert hashlib.sha256((json.dumps(upstream, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest() == SOURCE_SHA256
    assert len(CONTRACTS.model_names) == len(original["$defs"]) == 59
    assert set(CONTRACTS.model_names) == set(original["$defs"])
    for model in CONTRACTS.model_names:
        selected = CONTRACTS.schema(model)
        assert selected["$ref"] == "#/$defs/" + model
        assert selected["$defs"][model] == original["$defs"][model]
    assert (ROOT / "sdk/client-contracts.ts").read_text(encoding="utf-8") == typescript(document())


def test_native_source_availability_requires_consistent_provenance_or_typed_unavailability():
    unknown = {"available": False, "value": None, "reason_code": "native_source_provider_unavailable", "evidence_ref": None}
    assert CONTRACTS.validate("NativeSourceLookup", unknown) == unknown
    source = {"messageHandle": "message:synthetic:request", "operationId": "original-operation", "bindingEpoch": 1,
        "nativeTurnRef": "actual-turn", "nativeSession": {"providerRef": "trusted-provider", "sessionRef": "original-session",
            "hostRef": "original-host", "generation": "original-generation", "authority": "harness"}}
    linked = {"available": True, "value": source, "reason_code": None, "evidence_ref": "driver-source:proof"}
    assert CONTRACTS.validate("NativeSourceLookup", linked) == linked
    for bad in (linked | {"value": None}, linked | {"reason_code": "guessed"}, linked | {"evidence_ref": None},
                unknown | {"value": source}, linked | {"provider_url": "https://arbitrary.invalid"}):
        with pytest.raises(ClientContractViolation):
            CONTRACTS.validate("NativeSourceLookup", bad)


def test_absent_draft_has_no_invented_timestamp_and_persisted_draft_requires_one():
    value = {"content": "", "attachment_refs": [], "revision": 0, "updated_at": None}
    assert CONTRACTS.validate("Draft", value) == value
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("Draft", value | {"revision": 1})
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("Draft", value | {"updated_at": "2026-11-06T00:00:00Z"})
    assert CONTRACTS.validate("Draft", value | {"revision": 1, "updated_at": "2026-11-06T00:00:00Z"})


def test_legacy_notice_timestamp_is_unknown_without_inventing_a_migration_date():
    value = {"notice_handle": "notification:synthetic:communication-1", "source": "acs_system",
        "kind": "communication_obstacle", "message_ref": None, "receiver_ref": None,
        "reason_code": "delivery_unconfirmed", "summary": "Delivery needs observation.",
        "own_delivery": None, "seen": False, "revision": 1, "created_at": None}
    assert CONTRACTS.validate("Notice", value) == value
    assert CONTRACTS.validate("Notice", value | {"created_at": "2026-11-06T00:00:00Z"})
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("Notice", value | {"created_at": "adoption time"})


def test_generated_types_preserve_nullable_and_conditional_shapes():
    generated = typescript(document())
    assert "export type RecoveryRequest" in generated
    assert 'readonly "operation_ref": string;' in generated
    assert 'readonly "target_endpoint_ref": string;' in generated
    assert 'readonly "agent_slot_id": (string) | (null);' in generated
    native = generated.split("export type NativeAdmissionResult =", 1)[1]
    assert 'readonly "outcome": "accepted" | "queued" | "unknown";' in native
    assert 'readonly "effect_possible"?: true;' in native


@pytest.mark.parametrize("model,fields", [("NativeLink", ["host_ref", "provider_generation"]),
                                        ("NativeLinkWrite", ["expected_host_ref", "expected_provider_generation"])])
def test_native_link_host_and_generation_are_required_optimistic_identity(model, fields):
    body = {"address": "collaborator:p:slot", "receiver_ref": "receiver", "provider_ref": "admitted-provider",
        "native_session_ref": "actual-session", "native_authority": "harness"}
    if model == "NativeLink":
        body.update(link_id="link", project_id="p", binding_epoch=1, capabilities=[], revision=1,
                    host_ref="actual-host", provider_generation="actual-generation")
    else:
        body.update(expected_binding_epoch=1, expected_revision=0,
                    expected_host_ref="actual-host", expected_provider_generation="actual-generation")
    assert CONTRACTS.validate(model, body) == body
    for field in fields:
        invalid = {key: value for key, value in body.items() if key != field}
        with pytest.raises(ClientContractViolation):
            CONTRACTS.validate(model, invalid)


@pytest.mark.parametrize("field", ["attachment_total_bytes", "attachment_staging_bytes", "attachment_project_staging_bytes", "attachment_staging_seconds"])
def test_meta_requires_actual_aggregate_staging_limits_even_when_feature_is_disabled(field):
    value = {"schema_version": "acs-client/1", "server_version": "synthetic", "authority_id": "synthetic-authority",
        "authority_incarnation": "synthetic-incarnation", "features": [],
        "limits": {"message_bytes": 262144, "page_items": 100, "attachment_bytes": 1, "attachment_count": 0,
            "event_replay_seconds": 0, "attachment_total_bytes": 0, "attachment_staging_bytes": 0,
            "attachment_project_staging_bytes": 0, "attachment_staging_seconds": 0,
            "native_link_count": 0, "native_link_history_revisions": 0, "native_link_write_receipts": 0, "native_link_metadata_bytes": 0},
        "adapter_protocol": "acs-adapter/1", "event_protocol": "acs-event/1"}
    assert CONTRACTS.validate("Meta", value) == value
    invalid = deepcopy(value)
    del invalid["limits"][field]
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("Meta", invalid)
    for bad in (-1, True, "0"):
        invalid["limits"][field] = bad
        with pytest.raises(ClientContractViolation):
            CONTRACTS.validate("Meta", invalid)


def test_validate_returns_owned_data_and_never_injects_defaults_or_identity():
    source = {"to": "collaborator:synthetic:b", "content": "Natural text"}
    result = CONTRACTS.validate("SendRequest", source)
    assert result == source and result is not source
    assert "activation" not in result and "sender" not in result
    value = CONTRACTS.schema("SendRequest")
    value["$defs"]["SendRequest"]["properties"]["sender"] = {"type": "string"}
    assert "sender" not in CONTRACTS.schema("SendRequest")["$defs"]["SendRequest"]["properties"]


@pytest.mark.parametrize("extra", [{"sender": "forged-root"}, {"principal_ref": "forged"},
    {"task_id": "task"}, {"run_id": "run"}, {"native_session_id": "session"}])
def test_send_rejects_caller_supplied_author_and_execution_prerequisites(extra):
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("SendRequest", {"to": "b", "content": "A message", **extra})


def test_client_without_a_slot_is_schema_valid_but_does_not_gain_authority():
    actor = {"address": "client:synthetic:client", "principal_ref": "synthetic-principal", "level": "client",
             "agent_slot_id": None, "auth_revision": "synthetic-revision", "allowed_actions": []}
    assert CONTRACTS.validate("Actor", actor)["agent_slot_id"] is None
    # Validation does not manufacture a Slot or allow action, or authenticate it.
    assert CONTRACTS.validate("Actor", actor)["allowed_actions"] == []


def test_unknown_native_and_real_explicit_reply_are_independent():
    value = CONTRACTS.validate("DeliveryFacts", delivery())
    assert value["native"]["state"] == "unknown" and value["response"]["present"]
    assert value["consumption"]["state"] == "unobservable"


@pytest.mark.parametrize("change", [
    lambda value: value["native"].update(state="accepted", evidence_ref=None),
    lambda value: value["native"].update(state="accepted", operation_ref=None, evidence_ref="synthetic:ack"),
    lambda value: value["consumption"].update(state="observed", evidence_ref=None),
    lambda value: value["response"].update(present=True, message_handle=None),
    lambda value: value["response"].update(present=False),
    lambda value: value.update(accepted_by_authority=False),
])
def test_evidence_shape_cannot_invent_ack_consumption_or_agent_reply(change):
    value = delivery()
    change(value)
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("DeliveryFacts", value)


@pytest.mark.parametrize("state,effect,evidence", [("unknown", True, None),
    ("accepted", True, "synthetic:actual-native-ack"), ("definitively_not_admitted", False, "synthetic:no-effect-proof"),
    ("unsupported", False, None)])
def test_native_wire_outcomes_match_implemented_receiver_semantics(state, effect, evidence):
    value = {"schema_version": "acs-adapter/1", "operation_id": "native:synthetic", "outcome": state,
        "effect_possible": effect, "evidence_ref": evidence, "native_input_ref": None,
        "binding_epoch": 1, "provider_generation": "synthetic-generation", "reason_code": None}
    assert CONTRACTS.validate("NativeAdmissionResult", value) == value
    assert NativeAdmissionResult.model_validate_json(json.dumps(value)).outcome == state


@pytest.mark.parametrize("change", [{"outcome": "unknown", "effect_possible": False},
    {"outcome": "accepted", "effect_possible": True},
    {"outcome": "definitively_not_admitted", "effect_possible": False},
    {"outcome": "unsupported", "effect_possible": True}])
def test_native_wire_requires_positive_or_negative_evidence_without_erasing_unknown(change):
    value = {"schema_version": "acs-adapter/1", "operation_id": "native:synthetic", "outcome": "unknown",
        "effect_possible": True, "evidence_ref": None, "native_input_ref": None,
        "binding_epoch": 1, "provider_generation": "synthetic-generation", "reason_code": None, **change}
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("NativeAdmissionResult", value)


@pytest.mark.parametrize("action", ["reconcile", "retry_delivery", "rebind_receiver"])
@pytest.mark.parametrize("value", ["absent", None, ""])
def test_recovery_condition_requires_the_actual_operation_or_target(action, value):
    request = {"action": action, "expected_revision": 1, "reason": "Synthetic recovery"}
    key = "target_endpoint_ref" if action == "rebind_receiver" else "operation_ref"
    if value != "absent":
        request[key] = value
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("RecoveryRequest", request)


def test_recovery_inspect_and_bound_rebind_are_valid_but_not_executed():
    assert CONTRACTS.validate("RecoveryRequest", {"action": "inspect", "expected_revision": 0, "reason": "Inspect"})
    assert CONTRACTS.validate("RecoveryRequest", {"action": "rebind_receiver", "expected_revision": 1,
        "reason": "Authorized selection change", "target_endpoint_ref": "receiver:synthetic"})
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("RecoveryRequest", {"action": "inspect", "expected_revision": True, "reason": "Inspect"})


@pytest.mark.parametrize("timestamp", ["not-a-date", "2026-11-06T02:00:00", "2026-02-30T02:00:00Z",
    "2026-11-06 02:00:00Z", "2026-11-06T25:00:00Z", "2026-11-06T02:00:00+01:99"])
def test_date_time_checks_are_enforced_without_optional_jsonschema_format_dependencies(timestamp):
    value = message()
    value["committed_at"] = timestamp
    with pytest.raises(ClientContractViolation) as failure:
        CONTRACTS.validate("Message", value)
    assert failure.value.keyword == "format"


@pytest.mark.parametrize("timestamp", ["2026-11-06T02:00:00Z", "2026-11-06T11:00:00+09:00",
    "2026-11-06t02:00:00.123456789z"])
def test_aware_wire_timestamps_and_utf8_body_are_preserved(timestamp):
    value = message()
    value["committed_at"] = timestamp
    assert CONTRACTS.validate("Message", value) == value


@pytest.mark.parametrize("keyword,reference", [("$ref", "https://untrusted.invalid/schema"),
    ("$ref", "#/$defs/Missing"), ("$dynamicRef", "https://untrusted.invalid/dynamic"),
    ("$recursiveRef", "#"), ("$otherRef", "https://untrusted.invalid/extension")])
def test_schema_resolution_never_retrieves_remote_or_extension_references(keyword, reference):
    value = document()
    value["$defs"]["SendRequest"] = {keyword: reference}
    with pytest.raises(ClientContractSourceError):
        _safe_document(value)


def test_recursive_local_schema_is_rejected_before_validation():
    value = document()
    value["$defs"]["SendRequest"] = {"$ref": "#/$defs/SendRequest"}
    with pytest.raises(ClientContractSourceError, match="recursive"):
        _safe_document(value)


def test_data_reference_strings_are_data_not_schema_fetches():
    error = {"code": "synthetic", "message": "Safe detail", "retryable": False,
        "effect_state": "none", "operation_ref": None,
        "details": {"$ref": "https://untrusted.invalid/not-a-schema"}}
    assert CONTRACTS.validate("Error", error) == error


@pytest.mark.parametrize("payload", [float("nan"), {1: "bad key"}, object(), {"data": (1, 2)}])
def test_only_finite_bounded_json_values_enter_schema_validation(payload):
    with pytest.raises(ClientContractViolation):
        CONTRACTS.validate("Empty", payload)


def test_deep_or_circular_data_fails_with_a_redacted_resource_error():
    cyclic = {}
    cyclic["private-body-token"] = cyclic
    with pytest.raises(ClientContractViolation) as failure:
        CONTRACTS.validate("Empty", cyclic)
    assert failure.value.keyword == "json_resource_limit"
    assert "private-body-token" not in str(failure.value)


def test_validation_error_never_echoes_private_body_or_mutates_input():
    source = {"to": "b", "content": "private synthetic body", "sender": "private synthetic identity"}
    before = deepcopy(source)
    with pytest.raises(ClientContractViolation) as failure:
        CONTRACTS.validate("SendRequest", source)
    assert source == before
    assert "private synthetic" not in str(failure.value)
    with pytest.raises(ClientContractSourceError):
        CONTRACTS.schema("UnknownModel")
