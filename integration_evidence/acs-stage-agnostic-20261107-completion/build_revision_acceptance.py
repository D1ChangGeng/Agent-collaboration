"""Bind the v1.1 acceptance map to actual passing cases and captured bytes."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'runtime').is_dir())
OUT = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
PRIOR = ROOT / "integration_evidence/acs-stage-agnostic-20261106"
PACK = ROOT / "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0"
RUNS = ["p2-initial", "exact-completion-b", "core-components-final", "native-fences-components-final", "read-compatibility-final", "p0-p1-final"]
REVIEWED_DELTA = {"runtime/communication_http.py", "runtime_tests/test_communication_http_auth.py"}

P0 = {
    "T001": ["test_public_work_free_a_b_loop"],
    "T002": ["test_invalid_or_forged_input_has_no_message_side_effect"],
    "T003": ["test_trusted_unbound_client_receives_real_reply_without_a_fake_slot"],
    "T004": ["test_bound_slot_cannot_claim_another_slot_or_gain_management"],
    "T005": ["test_ready_target_rebind_retains_unknown_input_and_only_new_messages_use_new_epoch"],
    "T006": ["test_configuration_selects_one_real_receiver_and_rejects_another_slots_receiver"],
    "T007": ["test_t008_killed_writer_cannot_ack_or_leave_partial_message_reply_outbox_or_event"],
    "T008": ["test_t008_killed_writer_cannot_ack_or_leave_partial_message_reply_outbox_or_event"],
    "T009": ["test_t009_same_request_key_across_device_connections_has_one_committed_operation"],
    "T010": ["test_retry_uses_original_operation_and_conflict_preserves_content"],
    "T011": ["test_one_reply_can_cover_multiple_same_peer_requests"],
    "T012": ["test_third_party_cannot_read_or_answer_private_request"],
    "T013": ["test_native_activation_is_real_but_native_final_is_not_a_reply"],
    "T014": ["test_uncertain_native_ack_never_replays_and_does_not_block_real_reply"],
    "T015": ["test_message_only_never_invokes_and_future_reply_satisfies", "test_message_only_reaches_a_valid_slot_without_a_native_endpoint"],
    "T016": ["test_reply_survives_timeout_and_new_runtime_instance", "test_wait_database_disconnect_keeps_original_handle_and_resumes_without_resending"],
    "T017": ["test_read_preserves_inbox_and_long_utf8_content_continues", "test_t094_large_original_and_reply_keep_independent_wait_read_continuations"],
    "T018": ["test_read_preserves_inbox_and_long_utf8_content_continues"],
    "T019": ["test_inbox_and_history_page_in_authority_order_with_concurrent_senders"],
    "T020": ["test_query_filter_change_restarts_pagination"],
    "T021": ["test_handoff_is_durable_before_native_dispatch_and_not_part_of_prompt"],
    "T022": ["test_unknown_handoff_reconciles_original_input_without_resubmission"],
    "T023": ["test_signed_prepare_admission_replay_and_reconcile_use_one_original_native_input"],
    "T024": ["test_prepared_generation_cannot_be_moved_to_a_replacement_session"],
    "T025": ["test_unknown_handoff_reconciles_original_input_without_resubmission"],
    "T026": ["test_unknown_original_input_cannot_be_retried_into_a_new_attempt"],
    "T027": ["test_expired_lease_can_be_reclaimed_but_old_worker_never_executes"],
    "T028": ["test_readonly_signed_prepare_and_unsupported_admission_never_enter_native"],
    "T029": ["test_reauthorization_after_capacity_read_stops_creation_and_input"],
    "T030": ["test_post_submit_authorization_loss_preserves_unknown_effect_without_receipt_disclosure"],
    "T031": ["test_busy_is_separate_from_blocker_and_never_implies_safe_queue", "test_unsupported_input_modes_do_not_type_into_a_terminal"],
    "T032": ["test_busy_or_human_input_blockers_defer_before_native_marker", "test_exact_current_native_prompts_block_automatic_input"],
    "T033": ["test_stale_native_readback_is_unknown_instead_of_restamped"],
    "T034": ["test_readonly_describe_and_observe_do_not_prepare_or_claim_a_native_session"],
    "T035": ["test_ready_target_rebind_retains_unknown_input_and_only_new_messages_use_new_epoch"],
    "T036": ["test_changed_generation_preserves_positive_facts_and_never_submits_input"],
    "T037": ["test_existing_native_probe_uses_real_message_less_read_capability_and_resume"],
    "T038": ["test_missing_profile_or_reservation_signs_unknown_without_native_contact"],
    "T039": ["test_bidirectional_sync_commits_before_wait_and_avoids_duplicate_native", "test_active_reply_wait_precedes_message_wake_and_expiry_preserves_the_same_reply"],
    "T040": ["test_first_message_wake_does_not_coalesce_distinct_durable_message_bodies"],
    "T057": ["test_stalled_synthetic_transport_resyncs_from_last_yielded_cursor_not_queued_producer_position"],
    "T058": ["test_backoff_yields_to_another_due_operation_without_changing_original_intent"],
    "T061": ["test_normal_send_native_read_reply_wait_and_history_do_not_need_task_tables"],
    "T062": ["test_shared_attached_never_proves_dedicated_input_or_absent_user_draft"],
    "T069": ["test_operator_dry_run_and_idempotent_adoption_preserve_exact_original_after_task_exit", "test_explicit_adoption_preserves_every_legacy_byte_hash_result_event_and_sequence"],
    "T070": ["test_failed_adoption_rolls_back_ddl_copy_metadata_and_old_evidence", "test_unknown_legacy_input_blocks_lifecycle_after_adoption_without_new_rows"],
    "T071": ["test_idempotent_replay_precedes_receiving_revision_cas_but_not_authorization"],
    "T072": ["test_expected_revision_is_receiver_binding_not_attempt_or_team_revision"],
    "T073": ["test_arbitrary_diagnostic_text_never_enters_notice_payload"],
    "T074": ["test_communication_fault_notice_is_not_an_agent_reply"],
    "T075": ["test_readonly_describe_and_observe_do_not_prepare_or_claim_a_native_session"],
    "T076": ["test_known_unsupported_capability_is_preserved_without_inventing_support"],
    "T077": ["test_changed_files_or_receiving_generation_return_unknown_without_preparation"],
    "T078": ["test_every_represented_committed_peer_change_invalidates_cached_adapter"],
    "T079": ["test_t090_installed_wheel_maintains_committed_message_after_its_client_process_exits"],
    "T080": ["test_t090_installed_wheel_maintains_committed_message_after_its_client_process_exits", "test_heartbeats_have_no_effect_and_disconnect_cancels_producer_and_refresh"],
    "T089": ["test_self_foreign_project_and_known_foreign_pair_refs_do_not_grant_membership", "test_valid_attachment_from_other_project_cannot_be_saved_in_this_private_draft"],
    "T090": ["test_t090_installed_wheel_maintains_committed_message_after_its_client_process_exits"],
    "T091": ["test_t091_atomic_historical_adoption_resumes_after_rollback_without_guessing_missing_author"],
    "T092": ["test_registered_active_endpoint_has_unknown_native_facts_without_lifecycle_or_legacy_ready_inference"],
    "T093": ["test_missing_adoption_verification_is_read_only_and_base_still_valid", "test_default_open_preserves_legacy_schema_and_requires_explicit_adoption"],
    "T094": ["test_t094_large_original_and_reply_keep_independent_wait_read_continuations"],
    "T096": ["test_uncertain_lifecycle_never_executes_again_or_allows_fresh_source", "test_unknown_handoff_reconciles_original_input_without_resubmission"],
}
P2 = {
    "T043": ["test_t043_two_device_service_cas_never_regresses_frontier_or_consumes_messages"],
    "T044": ["test_private_view_updates_do_not_change_original_messages_consumption_or_replies"],
    "T051": ["test_message_participant_download_starts_only_after_atomic_actual_association"],
    "T052": ["test_same_principal_slots_and_root_manager_cannot_read_private_uploads", "test_t052_attachment_url_fields_never_fetch_and_guessed_private_ids_are_not_readable"],
    "T084": ["test_all_thirteen_p2_apis_and_t084_draft_conflict_across_real_http_connections"],
    "T085": ["test_real_asgi_disconnect_retains_exact_chunks_and_full_retry_resumes_original_plan"],
    "T088": ["test_all_thirteen_p2_apis_and_t084_draft_conflict_across_real_http_connections", "test_notice_seen_replays_original_full_result_before_stale_cas"],
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    now = datetime.now(UTC).isoformat()
    witnesses = defaultdict(list)
    runs = []
    for name in RUNS:
        data = read(OUT / (name + ".json"))
        assert data["returncode"] == 0 and not data["changed_sources"], name
        drift = [p for p, value in data["fixed_before"].items() if not (ROOT / p).is_file() or file_hash(ROOT / p) != value]
        assert set(drift) <= REVIEWED_DELTA, (name, drift)
        if name in {"read-compatibility-final", "p0-p1-final"}:
            assert not drift, (name, drift)
        runs.append({"id": name, "result": name + ".json", "log": name + ".log", "junit": name + ".xml",
                     "counts": data["counts"], "evidence_class": data["evidence_class"],
                     "source_files": len(data["fixed_before"]), "captured_files_match_current": not drift,
                     "reviewed_current_delta": drift,
                     "delta_verification": "Current p0-p1-final reruns the complete P0/P1 batch plus exact P2/installed-package/SSRF and real SDK acceptance. Earlier component/storage evidence is retained on unchanged owning mechanisms." if drift else None})
        grouped = Counter()
        for case in ET.parse(OUT / (name + ".xml")).iter("testcase"):
            if not any(case.find(t) is not None for t in ("failure", "error", "skipped")):
                key = case.get("classname").replace(".", "/") + ".py::" + case.get("name").split("[", 1)[0]
                grouped[key] += 1
        for key, count in grouped.items():
            witnesses[key].append({"run": name, "parameter_cases": count})

    functions = defaultdict(list)
    for path in (ROOT / "runtime_tests").glob("test_*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                functions[node.name].append(path.relative_to(ROOT).as_posix() + "::" + node.name)

    def evidence(names):
        result = []
        for name in names:
            assert len(functions[name]) == 1, (name, functions[name])
            reference = functions[name][0]
            assert witnesses[reference], ("required witness did not pass", reference)
            result.append({"test": reference, "current_passing_evidence": witnesses[reference]})
        return result

    tiered = {x["id"]: x for x in read(PACK / "contracts/scenario-scope.json")["scenarios"]}
    original = read(ROOT / "RFC_TEMP_SOURCE/ACS-Core-Cross-Harness-DevPack-v1.0.0/tests/scenarios.json")["scenarios"]
    assert set(P0) == {k for k, v in tiered.items() if v["tier"] == "P0_required"}
    assert set(P2) == {k for k, v in tiered.items() if v["tier"] == "P2_optional"}
    p1 = {x["id"]: x for x in read(PRIOR / "p1-current-20261107/p1-exit-audit.json")["scenarios"]}
    cases = []
    for row in original:
        identifier, tier = row["id"], tiered[row["id"]]["tier"]
        item = {key: row[key] for key in ("id", "title", "given", "when", "then")}
        item.update(tier=tier, original_gwt_preserved=True)
        if tier == "P1_required":
            old = p1[identifier]
            verified = []
            for source in old["current_evidence"]:
                reference = source.get("test")
                if reference and reference.startswith("runtime_tests/"):
                    assert witnesses[reference], (identifier, reference)
                    verified.append({"test": reference, "current_passing_evidence": witnesses[reference]})
                elif reference and reference.startswith("sdk/tests/"):
                    assert (ROOT / reference).is_file()
                    verified.append({"test_module": reference, "current_passing_evidence": "sdk-verification.json (all 210 tests)"})
            assert verified, identifier
            item.update(status="verified_P1_service_or_delegation_contract", prior_exact_audit=old,
                        current_evidence=verified, actual_Orca_Host=False)
        else:
            item.update(status="verified_applicable_service_and_safety_contract", evidence=evidence((P0 if tier == "P0_required" else P2)[identifier]))
        if identifier == "T006":
            item.update(status="verified_revised_legacy_compatibility", exact_old_gwt_passed=False,
                resolution="v1.1 P0-01 preserves the existing MCP precommit endpoint_binding_ambiguous rejection; P0-03 requires zero broadcast. An explicit endpoint or message_only remains the supported submission. Do not relabel the old inbox-commit expectation as passed.")
        if identifier == "T031":
            item.update(status="unsupported_verified", native_enqueue_qualified=False,
                resolution="No currently claimed Native profile attests safe enqueue. Busy stays deferred and queue/steer are typed unsupported. The original verified-enqueue Given is not applicable to this support set.")
        if identifier == "T037":
            item["scope"] = "Same live, owned Native session warm resume, with signed current authority and exact readback. Stopped-process cold recovery is not claimed."
        if identifier in {"T062", "T075", "T076"}:
            item["report_witness"] = "qualification-matrix.json; explicitly bounded evidence and unqualified configurations"
        if identifier == "T061":
            item["native_witness"] = "retained-native-evidence.json; E4 original A/B exchange, explicit reply and satisfied wait"
        if identifier == "T090":
            item["scope"] = "Actual current wheel installed into a temporary isolated target; standalone service survives client exit. Controlled Native callback, not a production service-manager deployment."
        cases.append(item)

    native = read(PRIOR / "native-agent-e2e-20261107/native-e2e-e.json")
    assert native["returncode"] == 0 and native["owned_tree_stopped"] and not native["changed_sources"]
    native_drift = [p for p, value in native["fixed_before"].items() if file_hash(ROOT / p) != value]
    assert set(native_drift) <= REVIEWED_DELTA, native_drift
    impact = read(OUT / "source-impact-review.json")
    assert impact["reverse_patch_matches_captured_before"]
    assert impact["before_sha256"] == native["fixed_before"]["runtime/communication_http.py"]
    assert impact["after_sha256"] == file_hash(ROOT / "runtime/communication_http.py")
    retained = {"schema_version": "acs-retained-native-evidence/1", "checked_at": now,
        "artifact": "integration_evidence/acs-stage-agnostic-20261106/native-agent-e2e-20261107/native-e2e-e.json",
        "sha256": file_hash(PRIOR / "native-agent-e2e-20261107/native-e2e-e.json"),
        "captured_files": len(native["fixed_before"]), "all_captured_files_match_current": not native_drift,
        "reviewed_delta": native_drift,
        "delta_impact": "Only the ordinary communication HTTP read facade and its regression fixture changed. The Native effect stack, signed receiver transport and actual Project/MCP send/reply/wait path used in e are byte-identical. The facade change is independently exercised in read-compatibility-final and p0-p1-final; this is not a newly executed E4 run.",
        "new_test_files_not_in_original_capture": ["runtime_tests/test_communication_p2_exact_scenarios.py",
            "runtime_tests/test_communication_commit_crash.py", "runtime_tests/test_communication_installed_maintenance.py",
            "runtime_tests/test_communication_attachment_ssrf.py"],
        "facts": read(PRIOR / "native-agent-e2e-20261107/current-cross-harness-result-e.json"),
        "note": "Historical run retained on exact captured bytes; no model/API call was repeated by this continuation."}
    sdk = read(OUT / "sdk-verification.json")
    assert sdk["source_unchanged"] and all(x["returncode"] == 0 for x in sdk["checks"])
    static = read(OUT / "static-verification.json")
    assert len(static["checks"]) == 7 and all(x["returncode"] == 0 for x in static["checks"])
    actual_p2 = next(p.get("value").split(",") for p in ET.parse(OUT / "p0-p1-final.xml").iter("property")
                     if p.get("name") == "p2_operation_ids")
    api_scope = read(PACK / "contracts/api-scope.json")["operations"]
    assert set(actual_p2) == {x["operation_id"] for x in api_scope if x["tier"] == "P2_optional"}
    report = {"schema_version": "acs-v11-completion-audit/1", "observed_at": now,
        "request_scope": "P0, P1 and explicitly requested P2 extensions",
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "working_tree": "dirty_uncommitted", "committed": False, "pushed": False, "receiver_sync_action": "none",
        "runs": runs, "scenario_count": len(cases), "scenario_tiers": dict(Counter(x["tier"] for x in cases)),
        "api_operations": [{**x, "status": "verified_current_service_contract",
            "actual_witness": "runtime_tests/test_communication_p1_headless_live.py::test_actual_production_sdk_p1_episode_covers22_operations_without_any_p2_calls"
                if x["tier"] == "P1_required" else "runtime_tests/test_communication_p2_exact_scenarios.py::test_all_thirteen_p2_apis_and_t084_draft_conflict_across_real_http_connections"}
            for x in api_scope],
        "scenario_statuses": dict(Counter(x["status"] for x in cases)), "scenarios": cases,
        "milestones": {"CORE_P0_QUALIFIED": "qualified_with_specific_blockers", "CLIENT_P1_CONTRACT_READY": True,
                       "P2_EXTENSIONS_READY": True, "ORCA_HOST_QUALIFIED": False},
        "limits": ["Actual Orca Host input extension and remote original-journal reader are unavailable; typed Host/source fallback is verified.",
                   "Physical multi-machine, Windows Shared/restricted Native and automatic stopped-process cold recovery are not qualified.",
                   "WSL Native cleanup proves its owned process group, not complete descendant containment.",
                   "Current P2 service qualification does not claim Native attachment injection or a new Claude/Pi Driver.",
                   "Legacy T006 is deliberately resolved through the revision's higher-priority MCP compatibility invariant, not declared an exact old-scenario pass."],
        "implementation_complete_within_declared_scope": True, "production_changes": False}
    (OUT / "acceptance-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "retained-native-evidence.json").write_text(json.dumps(retained, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scenarios": len(cases), "statuses": report["scenario_statuses"], "milestones": report["milestones"]}))


if __name__ == "__main__":
    main()
