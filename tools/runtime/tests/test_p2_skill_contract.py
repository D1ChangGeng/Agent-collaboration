from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "docs" / "runtime" / "skills"
SKILL_CONTRACT = ROOT / "docs" / "runtime" / "p2-skill-contract.json"
TOOL_CONTRACT = ROOT / "docs" / "runtime" / "p2-mcp-tool-contract.json"
EXPECTED = {
    "agent-collaboration-setup": {"list_projects", "load_project"},
    "acs-project-manager": {"load_project", "list_routes", "list_work"},
    "acs-delegate-work": {"create_work", "send_message", "list_harnesses"},
    "acs-handoff-work": {"handoff_work", "read_source"},
    "acs-review-work": {"request_review", "submit_review", "read_diff"},
    "acs-finalize-work": {"accept_work", "list_reviews", "list_evidence"},
    "acs-recover-work": {"check_inbox", "list_activity", "read_source"},
    "acs-portfolio-manager": {"list_projects", "load_project", "list_routes"},
}


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---" + chr(10)):
        raise AssertionError("SKILL.md frontmatter missing")
    raw = text.split("---", 2)[1]
    values = {}
    for line in raw.strip().splitlines():
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


class P2SkillContractTests(unittest.TestCase):
    def test_machine_catalog_matches_skill_specs_and_tools(self):
        skill_contract = json.loads(SKILL_CONTRACT.read_text(encoding="utf-8"))
        tool_contract = json.loads(TOOL_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(skill_contract["surface_revision"], tool_contract["surface_revision"])
        self.assertEqual(set(skill_contract["skills"]), set(EXPECTED))
        for name, entry in skill_contract["skills"].items():
            with self.subTest(skill=name):
                self.assertEqual(entry["spec"], f"skills/{name}/SKILL.md")
                self.assertTrue(entry["goal"])
                self.assertTrue(entry["triggers"])
                self.assertTrue(set(entry["required_tools"]) <= set(tool_contract["tools"]))

    def test_runtime_skill_catalog_is_complete(self):
        actual = {
            path.parent.name
            for path in SKILLS.glob("*/SKILL.md")
        }
        self.assertEqual(actual, set(EXPECTED))

    def test_each_skill_has_portable_identity_and_required_tools(self):
        for name, tools in EXPECTED.items():
            path = SKILLS / name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            meta = frontmatter(text)
            with self.subTest(skill=name):
                self.assertEqual(meta["name"], name)
                self.assertTrue(meta["description"])
                self.assertRegex(name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                for tool in tools:
                    self.assertIn(tool, text)

    def test_catalog_includes_setup_and_starter_prompts(self):
        catalog = (SKILLS / "README.md").read_text(encoding="utf-8")
        prompts = (SKILLS / "STARTER-PROMPTS.md").read_text(encoding="utf-8")
        self.assertIn("agent-collaboration-setup", catalog)
        for name in EXPECTED:
            self.assertIn(name, catalog)
        for section in (
            "Project management", "Delegation", "Handoff", "Review",
            "Finalization", "Recovery", "Portfolio",
        ):
            self.assertIn(f"## {section}", prompts)

    def test_workflow_authority_is_skill_based(self):
        runtime_docs = ROOT / "docs" / "runtime"
        self.assertFalse(any(runtime_docs.rglob("*.command.md")))
        contract = (runtime_docs / "P2-MCP-WORKFLOW-CONTRACT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Reusable user workflows are Skills", contract)
        self.assertIn("Domain Command remains", contract)


if __name__ == "__main__":
    unittest.main()
