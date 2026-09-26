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
    "acs-project-context": {"list_projects", "load_project", "list_routes"},
    "acs-collaboration-model": {"configure_team", "create_work", "handoff_work"},
    "acs-runtime-model": {"list_connections", "list_harnesses", "stop_attempt"},
    "acs-continuity-recovery": {"check_inbox", "wait_for_response", "watch_changes"},
    "acs-source-evidence": {"list_sources", "read_source", "read_diff"},
    "acs-review-acceptance": {"request_review", "submit_review", "accept_work"},
    "acs-policy-governance": {"read_profile", "configure_team", "submit_command"},
    "acs-web-collaboration": {"list_projects", "load_project", "read_file"},
}
KNOWLEDGE = set(EXPECTED) - {"agent-collaboration-setup"}


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
    @classmethod
    def setUpClass(cls):
        cls.skill_contract = json.loads(SKILL_CONTRACT.read_text(encoding="utf-8"))
        cls.tool_contract = json.loads(TOOL_CONTRACT.read_text(encoding="utf-8"))

    def test_machine_catalog_matches_specs_and_tools(self):
        self.assertEqual(
            self.skill_contract["surface_revision"],
            self.tool_contract["surface_revision"],
        )
        self.assertEqual(self.skill_contract["model"], "metadata-first knowledge modules with lazy references")
        self.assertEqual(set(self.skill_contract["skills"]), set(EXPECTED))
        for name, entry in self.skill_contract["skills"].items():
            with self.subTest(skill=name):
                self.assertEqual(entry["spec"], f"skills/{name}/SKILL.md")
                self.assertTrue(entry["description"])
                self.assertTrue(entry["signals"])
                self.assertTrue(set(EXPECTED[name]) <= set(self.tool_contract["tools"]))
                self.assertTrue(set(entry.get("related_skills", [])) <= set(EXPECTED))

    def test_runtime_catalog_has_one_setup_exception_and_eight_knowledge_modules(self):
        actual = {path.parent.name for path in SKILLS.glob("*/SKILL.md")}
        self.assertEqual(actual, set(EXPECTED))
        kinds = {
            name: entry["kind"]
            for name, entry in self.skill_contract["skills"].items()
        }
        self.assertEqual(kinds["agent-collaboration-setup"], "guarded_setup")
        self.assertEqual(
            {name for name, kind in kinds.items() if kind == "knowledge_module"},
            KNOWLEDGE,
        )

    def test_knowledge_skills_are_routers_with_lazy_references(self):
        required_sections = {
            "## Knowledge boundary",
            "## Core invariants",
            "## Retrieval map",
            "## Tool vocabulary",
            "## Application",
            "## Related knowledge",
        }
        for name in KNOWLEDGE:
            directory = SKILLS / name
            text = (directory / "SKILL.md").read_text(encoding="utf-8")
            meta = frontmatter(text)
            with self.subTest(skill=name):
                self.assertEqual(meta["name"], name)
                self.assertTrue(required_sections <= set(
                    line for line in text.splitlines() if line.startswith("## ")
                ))
                for reference in ("model.md", "decisions.md", "tools.md"):
                    path = directory / "references" / reference
                    self.assertTrue(path.is_file())
                    self.assertIn(f"references/{reference}", text)
                    self.assertGreater(len(path.read_text(encoding="utf-8")), 200)
                for tool in EXPECTED[name]:
                    self.assertIn(tool, text + (directory / "references" / "tools.md").read_text(encoding="utf-8"))

    def test_runtime_presentation_is_metadata_first_and_selective(self):
        presentation = self.skill_contract["presentation"]
        self.assertEqual(presentation["initial"], "name and description metadata only")
        self.assertEqual(presentation["reference_loading"], "one named reference at a time")
        self.assertEqual(
            presentation["result_hint_fields"],
            ["skill", "topic", "reason", "reference"],
        )
        doc = (SKILLS / "RUNTIME-PRESENTATION.md").read_text(encoding="utf-8")
        for phrase in (
            "Stage 1: metadata",
            "Stage 2: domain router",
            "Stage 3: targeted reference",
            "Stage 4: project evidence",
            "Recall and context tradeoff",
            "Quality measures",
        ):
            self.assertIn(phrase, doc)

    def test_setup_skill_remains_guarded_and_procedural(self):
        text = (SKILLS / "agent-collaboration-setup" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("signed release installer", text)
        self.assertIn("project setup CLI", text)
        self.assertIn("OAuth", text)

    def test_high_level_command_documents_are_absent(self):
        runtime_docs = ROOT / "docs" / "runtime"
        self.assertFalse(any(runtime_docs.rglob("*.command.md")))
        contract = (runtime_docs / "P2-MCP-WORKFLOW-CONTRACT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Skills are domain knowledge modules", contract)
        self.assertIn("Domain Command remains", contract)


if __name__ == "__main__":
    unittest.main()
