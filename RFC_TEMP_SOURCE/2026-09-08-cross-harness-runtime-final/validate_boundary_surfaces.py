"""Validate the accepted external-Agent boundary across final package surfaces."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SURFACES = [
    "Architecture-RFC-v2.zh-CN.md",
    "architecture-decisions.json",
    "build-buy-integrate-extend-matrix.md",
    "capability-matrix.md",
    "acceptance-scenarios.json",
    "state-machines.json",
    "README.md",
    "not-run-product-facts.zh-CN.md",
    "deliverables.json",
    "validation-report.md",
    "validation-results.json",
]
REQUIRED = {
    "Architecture-RFC-v2.zh-CN.md": ["外部 Agent", "Collaboration System", "Durable Operation Provider"],
    "README.md": ["外部 Agent", "Agent Collaboration System"],
    "not-run-product-facts.zh-CN.md": ["not_run", "supported", "P1", "P2"],
}
FORBIDDEN = {
    "Management Agent Worker",
    "Management Worker",
    "Decision Worker",
    "Agent decision graph",
    "LangGraph as Worker",
    "active orchestration worker",
    "Spawn two workers",
    "Automatic worker owns workspace",
}

def main() -> None:
    for name in SURFACES:
        text = (ROOT / name).read_text(encoding="utf-8")
        missing = [term for term in REQUIRED.get(name, []) if term not in text]
        if missing:
            raise AssertionError(f"{name}: missing required boundary terms: {missing}")
        found = [term for term in FORBIDDEN if term in text]
        if found:
            raise AssertionError(f"{name}: forbidden boundary residue: {found}")
    schema = json.loads((ROOT / "scope-model.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    fixture = {
        "scope_id": "scope-root-1",
        "kind": "root",
        "parent_scope_id": None,
        "identity_ref": "root-1",
        "knowledge_refs": ["knowledge/root"],
        "policy_refs": ["policy/local"],
        "source_binding_ref": None,
        "collaboration_state_ref": "state/root-1",
        "created_by": "external-agent-slot:management-1",
        "created_at": "2026-09-09T00:00:00Z",
        "bindings": [{
            "binding_id": "binding-1",
            "scope_id": "scope-root-1",
            "agent_slot_id": "agent-slot-management-1",
            "role": "management",
            "authority": "authority-1",
            "location_ref": "workspace:management",
            "valid_from": "2026-09-09T00:00:00Z",
            "valid_until": None,
            "status": "active"
        }]
    }
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)
    print("PASS: external-Agent boundary, forbidden-residue, and Scope schema checks.")
    print("NOT RUN: real Harness, network, recovery, authorization and side-effect tests.")

if __name__ == "__main__":
    main()
