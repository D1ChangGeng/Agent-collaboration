"""Finalize the development objective only after current regressions are green.

Qualification is a separate axis. Historical Native artifacts are never
promoted to current-source or actual Orca qualification by this script.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "integration_evidence/acs-development-capabilities-20261107"
PRIOR = ROOT / "integration_evidence/acs-stage-agnostic-20261107-completion"
CANONICAL = ROOT / "integration_evidence/acs-stage-agnostic-20261106"
PACK = ROOT / "RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


REVIEW = {
    "C01": "MCP/HTTP share trusted ingress author and existing accepted Message/operation/Outbox facts; strict explicit reply, message_only, UTF-8 continuation and original request-key semantics remain intact.",
    "C02": "Typed adapter describe/observe captures actual profile, account, host, generation, evidence freshness and independent readiness axes. Unsupported and unknown never imply idle or input authority.",
    "C03": "Both concrete Drivers and signed Receiver recheck original operation, current authority, binding, owned transport and fresh readiness at the final handoff. Busy defers unless a separately proven Host queue is used; human blockers do not auto-submit.",
    "C04": "Original dispatch/DriverJournal markers precede possible effects. Unknown ACK stays in its original dedup domain; exact query can repair that same receipt, without a new invocation or explicit Agent reply.",
    "C05": "Core binding CAS, enrolled Node/Runtime revisions, local boot/execution fences and actual owned child identity reject replaced bindings. Historical ACKs remain attached only to their original operation.",
    "C06": "Independent maintenance advances due Messages under bounded scheduling and active-wait precedence. Repeated stopped-context restore archives lifecycle frames in the same Message Outbox, retaining original identity and possible-effect facts.",
    "C07": "Signed restore restarts only the proven stopped transport and resumes the exact retained Native session, including a positively known replacement session. Reconstructed factories reattest Core/profile/account/journal/complete-stop evidence. Explicit ready-target rebind remains a separately authorized CAS.",
    "C08": "Configured registered TLS peers retain original retry/ACK domains and bounded transport budgets. Current peer identity, signing-key/connection generation and readback are checked; absent mixed-version extensions fail typed and never fabricate an ACK.",
    "C09": "Storage and DriverJournal adoption remain explicit and additive. Normal startup verifies. Existing namespaces with lost journals cannot be recreated; retained current/archived Core startup facts also prohibit reset.",
    "C10": "Evidence runners record commands, source bytes, original failures, component/controlled-integration boundaries and candidate package identity. Actual Native/platform/Host qualification is separately pending after the current code changes, as excluded from this development stopping condition.",
    "C11": "Participant-authorized diagnostics expose only technical layers/reasons/evidence. Inspect/reconcile query original work; recovery commands require current management authority, expected revision and durable idempotent acceptance.",
    "C12": "Authenticated HTTP facade calls the same Domain and current permissions as MCP, with scope checks, bounded paging/body budgets, typed errors and original write keys; no parallel message ledger.",
    "C13": "Conversation is a rebuildable authorized participant-pair projection of actual Messages. Contacts support empty-history targets; send has no create-conversation prerequisite and history uses stable Authority order.",
    "C14": "Current profile/contact/receiver/delivery/operation/notice projections preserve unknown fields, exact private visibility and conditional permitted recovery actions.",
    "C15": "Frozen snapshot and high-water share a consistency boundary. Replay cursors bind identity/filter/auth state; dedup, revocation, resync and bounded slow-consumer behavior preserve authoritative Messages.",
    "C16": "Authorized NativeLink/source provenance follows exact original Core dispatch plus local DriverJournal or authenticated remote readback. Concrete Orca source derives from its original signed Host admission receipt. Separate identifiers/cursors/Host permissions remain intact; no text-similarity inference.",
    "C17": "The TypeScript Orca port and concrete Python existing-Core verifier/router provide trusted observe/admit/original reconcile composition on the existing Receiver ledger/TLS operations. Host owns serialized input and independent authorization; ACS does not own its Native Driver/PTY or mutate Orca storage.",
    "C18": "NativeView/Workspace delegate contracts cover Host-owned transcript/tool/Diff/approval/model/session/attachment actions with independent live Host grants and typed missing-port behavior; they do not copy Native state into ACS.",
    "C19": "Production SDK headless consumers use actual OAuth HTTP/PG, all P1 operations, explicit replies, history/receipts, snapshots/events/reconnect/revocation and typed Native-source/delegate behavior.",
    "C20": "All 30 source UI contracts map to ACS communication, activated P2 or an explicit Host delegate, with actions/data/events/degradation and contract witnesses. Product UI construction and actual Orca installation are not part of this backend pack.",
    "C21": "Current participant ACL and registration incarnation bracket local/remote source I/O; Receiver current technical-read policy is separate from expired input permission. Host read/control grants remain independent of ACS metadata or manager roles.",
    "C22": "Viewer-scoped monotonic read frontier, independent unread override and notice seen are isolated from Agent Inbox consumption and from other viewers.",
    "C23": "Viewer-scoped drafts/preferences/mute/archive use authenticated CAS and multi-device synchronization, preserving public conversation facts and current write/read permissions.",
    "C24": "Actual binary reservation/upload/finalize/download validates digest/size/MIME, ACL, quotas and lifecycle on the admitted Scope CAS. Arbitrary URL/local-path fetch is rejected. Communication attachments remain retrievable by authorized recipients; Native attachment conversion requires independently proven Host reachability and otherwise refuses before Native input.",
    "C25": "Bounded indexed full-text Message search uses current participant ACL and stable authorized cursors; neither counts nor results expose inaccessible messages.",
}

ADDITIONAL = {
    "C06": ["runtime/communication_message_wake.py", "runtime/communication_message_restore.py", "runtime/receiver_lifecycle_maintenance.py", "runtime_tests/test_message_cold_restore_pg.py"],
    "C07": ["runtime/native_restore.py", "runtime/native_restore_origin.py", "runtime/receiver_lifecycle_capacity.py", "runtime/receiver_lifecycle_contract.py", "runtime/receiver_lifecycle_node.py", "runtime/receiver_lifecycle_issuance.py", "runtime_deployment/receiver_lifecycle.py", "runtime_tests/test_native_cold_restore_transport.py", "runtime_tests/test_native_restore_origin.py", "runtime_tests/test_receiver_restore_factory_pg.py"],
    "C09": ["runtime_deployment/receiver_lifecycle.py", "runtime_tests/test_receiver_lifecycle_factory.py", "runtime_tests/test_receiver_restore_factory_pg.py"],
    "C10": ["tools/runtime/cross_harness_verify.py", "runtime_tests/native_e2e_isolation.py"],
    "C16": ["runtime/communication_client_native_source.py", "runtime/native_source_links.py", "runtime/remote_native_source.py", "runtime/receiver_models.py", "runtime/receiver_delivery.py", "runtime/remote_endpoint.py", "runtime/orca_receiver_backend.py", "runtime_tests/test_communication_remote_source_pg.py", "runtime_tests/test_remote_native_source_tls.py"],
    "C17": ["runtime/orca_receiver_backend.py", "runtime/remote_endpoint.py", "runtime_tests/test_orca_receiver_backend.py", "runtime_tests/test_communication_remote_source_pg.py"],
    "C21": ["runtime/communication_client_native_source.py", "runtime/receiver.py", "runtime_deployment/receiver_authority.py", "runtime_tests/test_remote_native_source_tls.py", "runtime_tests/test_communication_remote_source_pg.py"],
}


def main():
    now = datetime.now(UTC).isoformat()
    final = read(OUT / "development-final-integration-b.json")
    assert final["returncode"] == 0 and not final["changed_sources"]
    assert final["counts"]["failed"] == final["counts"]["errors"] == 0
    static = read(OUT / "development-static-b.json")
    assert len(static["checks"]) == 10 and all(x["returncode"] == 0 for x in static["checks"])
    package = read(OUT / "package-facts.json")
    assert package["source_and_installed_package_match"]
    for path, hashed in final["fixed_after"].items():
        assert digest(ROOT / path) == hashed, path
    for path, hashed in package["package_files"].items():
        assert digest(ROOT / path) == hashed, path
    source = {"repository": str(ROOT), "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
        "tracked_binary_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff", "HEAD"], cwd=ROOT)).hexdigest(),
        "working_tree": "dirty_uncommitted", "committed": False, "pushed": False,
        "upstream": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd=ROOT, text=True).strip(),
        "receiver_sync_action": "none", "observed_at": now}
    write(OUT / "source-state.json", source)
    write(OUT / "source-manifest.json", final["fixed_after"])
    old = read(OUT / "prior-adoption-state.json")
    previous = {x["id"]: x for x in old["items"]}
    changes = read(PACK / "contracts/change-items.json")["items"]
    assert set(REVIEW) == {x["id"] for x in changes} and len(changes) == 25
    items = []
    for item in changes:
        key = item["id"]
        paths = sorted({x["path"] for x in previous[key].get("observed_code", [])} | set(ADDITIONAL.get(key, [])))
        observed = [{"path": p, "sha256": digest(ROOT / p)} for p in paths]
        items.append(item | {"development_status": "complete", "remaining_development_items": [],
            "implementation_review": REVIEW[key], "observed_code": observed,
            "current_regression": relative(OUT / "development-final-integration-b.json"),
            "qualification": "separate; actual Native/Host/platform combinations are not inferred from controlled tests"})
    requirements = read(PACK / "contracts/requirements-scope.json")["requirements"]
    for row in requirements:
        owners = [x for x in items if row["id"] in x["old_requirements"]]
        assert owners, row["id"]
        row.update(development_status="complete", change_items=[x["id"] for x in owners],
            implementation_reviews=[x["implementation_review"] for x in owners], remaining_development_items=[])
    assert len(requirements) == 40
    tests = list(ET.parse(OUT / "development-final-integration-b.xml").getroot().iter("testcase"))
    passed = {x.attrib["name"].split("[")[0] for x in tests if not any(x.find(k) is not None for k in ("failure", "error", "skipped"))}
    api = read(PRIOR / "api-assessment.json")["operations"]
    expected_api = read(PACK / "contracts/api-scope.json")["operations"]
    assert {x["operation_id"] for x in api} == {x["operation_id"] for x in expected_api} and len(api) == 35
    for row in api:
        witness = row["actual_witness"].split("::")[-1].split("[")[0]
        assert witness in passed, (row["operation_id"], witness)
        row.update(development_status="complete", evidence=relative(OUT / "development-final-integration-b.xml"))
    ui = read(PACK / "contracts/ui-scope.json")["features"]
    assert len(ui) == 30
    for row in ui:
        row.update(development_status="contract_complete", actual_UI_or_Orca_Host_qualification=False,
            evidence=[relative(OUT / "development-static-b.json"), relative(OUT / "development-final-integration-b.xml")])
    ledger = {"schema_version": "acs-development-capability-audit/1", "observed_at": now, "source_state": source,
        "objective": "All P0/P1 and explicitly activated P2 development capabilities; qualification coverage is separate",
        "development_status": "complete", "change_item_counts": dict(Counter(x["tier"] for x in items)),
        "requirement_count": len(requirements), "api_count": len(api), "ui_contract_count": len(ui),
        "remaining_development_items": [], "items": items, "requirements": requirements,
        "api_operations": api, "ui_contracts": ui,
        "conditional_contracts": ["Safe native queue/steer requires a proven provider; busy otherwise defers.",
            "Actual Orca installs the independently authorized atomic Host extension; ACS-owned verifier/router is implemented.",
            "Native attachment conversion is a Host delegate requiring actual destination reachability; ACS binary service is implemented.",
            "Additional Claude/Pi full Drivers require an explicitly specified actual target/version and are conditional, outside the25 defined items."],
        "verification": {"integration": relative(OUT / "development-final-integration-b.json"), "counts": final["counts"],
            "static": relative(OUT / "development-static-b.json"), "package": relative(OUT / "package-facts.json")},
        "production_changes": False, "actual_model_calls": 0}
    supplementary = []
    for name in ("final-restore-source-components", "remote-source-current-read", "driver-warm-compatibility",
                 "wake-lost-ack-regression-b", "orca-core-remote-source-c", "restore-factory-core-b"):
        data = read(OUT / (name + ".json"))
        assert data["returncode"] == 0 and not data["changed_sources"]
        changed = [p for p, hashed in data["fixed_after"].items()
                   if (ROOT / p).is_file() and digest(ROOT / p) != hashed]
        supplementary.append({"path": relative(OUT / (name + ".json")), "counts": data["counts"],
            "current_product_source_match": not any(p.startswith(("runtime/", "runtime_deployment/", "sdk/")) for p in changed),
            "changed_sources_since_run": changed,
            "drift_review": "The later replacement-session restore extension is covered by final-restore-source-components; technical-read callback wiring is covered by remote-source-current-read and the final Core/TLS integration. The wire-test fixture now classifies original-session reads separately from mutations."})
    ledger["verification"]["supplementary_runs"] = supplementary
    ledger["verification"]["counting_rule"] = "Runs overlap; counts are not added into a single full-suite result. Current-source actual Native/Host qualification remains separate."
    ledger["verification"]["retained_failure_records"] = [
        relative(OUT / "development-final-integration.json"), relative(OUT / "development-final-integration-interruption.json"),
        relative(OUT / "wake-lost-ack-regression-a.json"), relative(OUT / "orca-core-remote-source-a.json"),
        relative(OUT / "orca-core-remote-source-b.json"), relative(OUT / "restore-factory-core-a.json")]
    write(OUT / "development-capabilities.json", ledger)
    qualification = {"schema_version": "acs-qualification-separation/1", "observed_at": now,
        "current_source": source, "current_component_and_controlled_integration": final["counts"],
        "current_source_Native_or_actual_Orca_qualified": False,
        "limits": ["The modified Driver/lifecycle stack needs fresh actual Native/version/OS qualification; historical E3/E4 is retained as historical evidence only.",
            "Actual Orca Host installation and E5 are unmeasured; current Host effects/lookup in regressions are explicit doubles.",
            "Physical two-machine and unmeasured Shared/restricted/platform combinations are not qualified by loopback TLS or Windows-to-WSL history.",
            "A POSIX owned-process-group stop proves that containment only, not escaped-descendant containment.",
            "The original96 scenarios are not all claimed to have executed unchanged; legacy MCP compatibility and conditional Native capability rules remain authoritative."],
        "historical_artifacts": [], "development_blockers": []}
    for p in (CANONICAL / "native-agent-e2e-20261107/native-e2e-e.json",
              CANONICAL / "native-history-contract-20261107/actual-native-lifecycle-pg-g.json",
              CANONICAL / "native-history-contract-20261107/opencode-wsl-lifecycle-pg-b.json"):
        data = read(p)
        drift = [name for name, hashed in data.get("fixed_before", {}).items()
                 if (ROOT / name).is_file() and digest(ROOT / name) != hashed and name.startswith(("runtime/", "runtime_deployment/"))]
        qualification["historical_artifacts"].append({"path": relative(p), "original_returncode": data.get("returncode"),
            "changed_current_product_sources": drift, "current_source_status": "requalification_required"})
    write(OUT / "qualification-matrix.json", qualification)
    state = read(CANONICAL / "adoption-state.json")
    state.update(observed_at=now, development_status="complete_full_development_capability_objective",
        source_head=source["head"], source_tree=source["tree"], branch=source["branch"], dirty_patch_digest=source["tracked_binary_diff_sha256"],
        development_audit=relative(OUT / "development-capabilities.json"), source_state=source,
        qualification_matrix=relative(OUT / "qualification-matrix.json"), final_report=relative(OUT / "FINAL_REPORT.md"),
        acceptance_audit=relative(OUT / "development-capabilities.json"), current_work_state=relative(OUT / "WORK_STATE.md"),
        remaining_development_items=[], active_runners=[], pg_lease="none", production_changes=False,
        milestones={"CORE_P0_DEVELOPMENT_COMPLETE": True, "CLIENT_P1_CONTRACT_READY": True, "P2_EXTENSIONS_READY": True,
                    "CORE_P0_QUALIFIED": "current_changed_Native_stack_requires_requalification", "ORCA_HOST_QUALIFIED": False},
        milestone_reason="All25 development items,40 mapped requirements,35 operations and30 UI/source contracts are implemented. Current actual Native/Host qualification is separate and is not inferred from historical source or doubles.",
        external_qualification_limits=qualification["limits"])
    current = {x["id"]: x for x in items}
    for row in state["items"]:
        reviewed = current[row["id"]]
        row.update(status="implemented_needs_evidence" if row["id"] in {"C02", "C03", "C04", "C05", "C06", "C07", "C08", "C10", "C16", "C17", "C21"} else "retained_verified",
            development_status="complete", assessed_at=now, assessment_scope=ledger["objective"],
            implementation_gaps_in_declared_scope=[], remaining_development_items=[], observed_code=reviewed["observed_code"],
            implementation_review=reviewed["implementation_review"], evidence_refs=[relative(OUT / "development-capabilities.json")],
            qualification_limit=relative(OUT / "qualification-matrix.json"), next_actions=[],
            prior_scenario_evidence=row.get("scenario_evidence", []),
            scenario_evidence=[{"status": "current_development_regression; actual Native/Host qualification is separate",
                                "detail": relative(OUT / "development-final-integration-b.json")}])
    write(CANONICAL / "adoption-state.json", state)
    print(json.dumps({"change_items": len(items), "requirements": len(requirements), "api_operations": len(api),
                      "ui_contracts": len(ui), "remaining_development_items": 0, "tests": final["counts"]}))


if __name__ == "__main__":
    main()


