from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_CONTRACT = ROOT / "docs" / "runtime" / "p2-mcp-tool-contract.json"
GATE_CONTRACT = ROOT / "docs" / "runtime" / "gate-contract.json"


class P2McpToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(TOOL_CONTRACT.read_text(encoding="utf-8"))
        cls.gates = json.loads(GATE_CONTRACT.read_text(encoding="utf-8"))

    def test_surface_groups_are_exact_and_names_are_concise(self):
        groups = self.catalog["tool_groups"]
        self.assertEqual(
            list(groups),
            [
                "global", "project_context", "project_lists", "project_reads",
                "source_reads", "project_actions", "continuation",
                "source_writes", "advanced",
            ],
        )
        names = [name for group in groups.values() for name in group]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(self.catalog["tools"]))
        self.assertIn("configure_team", names)
        self.assertIn("list_harnesses", names)
        self.assertNotIn("setup_collaboration", names)
        self.assertNotIn("find_harnesses", names)
        for name in names:
            self.assertIn(len(name.split("_")), (2, 3), name)

    def test_every_tool_has_selection_schema_security_and_result_metadata(self):
        annotation_fields = {
            "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"
        }
        for name, tool in self.catalog["tools"].items():
            with self.subTest(tool=name):
                self.assertTrue(tool["title"])
                self.assertTrue(tool["description"])
                self.assertTrue(tool["selection_guidance"])
                self.assertEqual(set(tool["annotations"]), annotation_fields)
                self.assertTrue(tool["input_schema"]["schema_version"])
                self.assertIsInstance(tool["security_scopes"], list)
                self.assertTrue(tool["security_scopes"])
                self.assertIn(tool["result_type"], self.catalog["result_types"])

    def test_result_types_match_the_exposed_surface(self):
        used = {tool["result_type"] for tool in self.catalog["tools"].values()}
        self.assertEqual(used, set(self.catalog["result_types"]))

    def test_project_id_is_explicit_on_every_project_tool(self):
        global_tools = set(self.catalog["project_context_rule"]["global_tools"])
        for name, tool in self.catalog["tools"].items():
            required = set(tool["input_schema"]["required"])
            if name in global_tools or name == "submit_command":
                continue
            with self.subTest(tool=name):
                self.assertIn("project_id", required)
        self.assertTrue(self.catalog["project_context_rule"]["handle_project_must_match_argument"])

    def test_team_configuration_matches_existing_scope_boundary(self):
        configure = self.catalog["tools"]["configure_team"]
        self.assertEqual(configure["result_type"], "team_configuration")
        required = set(configure["input_schema"]["required"])
        self.assertTrue(
            {
                "project_id", "scope_handle", "expected_revision", "members",
                "policies", "budgets",
            }
            <= required
        )
        self.assertNotIn("scope", required)

    def test_read_and_message_consumption_are_separate(self):
        resource = self.catalog["tools"]["read_resource"]
        message = self.catalog["tools"]["read_message"]
        self.assertTrue(resource["annotations"]["readOnlyHint"])
        self.assertFalse(message["annotations"]["readOnlyHint"])
        self.assertNotIn("consume", resource["input_schema"]["optional"])
        self.assertEqual(message["input_schema"]["defaults"]["consume"], True)
        self.assertTrue(
            {"summary", "detail", "content", "history", "evidence"}
            <= set(resource["input_schema"]["views"])
        )

    def test_send_wait_and_subscription_defaults_are_explicit(self):
        defaults = self.catalog["defaults"]
        self.assertEqual(defaults["response_mode"], "async")
        self.assertEqual(defaults["delivery_policy"], "queue_until_idle")
        send = self.catalog["tools"]["send_message"]["input_schema"]
        self.assertIn("response_mode", send["optional"])
        self.assertNotIn("response_mode", send["required"])
        self.assertEqual(send["response_modes"], ["async", "sync"])
        self.assertEqual(
            self.catalog["tools"]["wait_for_response"]["input_schema"]["modes"],
            ["any", "all"],
        )
        self.assertIn("watch_changes", self.catalog["tool_groups"]["continuation"])

    def test_profiles_limit_tool_discovery(self):
        profiles = self.catalog["profiles"]
        self.assertIn("load_project", profiles["root_manager"])
        self.assertIn("submit_review", profiles["reviewer"])
        self.assertNotIn("accept_work", profiles["reviewer"])
        self.assertIn("apply_patch", profiles["engineer"])
        self.assertEqual(
            profiles["operator"],
            ["read_profile", "list_projects", "list_connections", "submit_command"],
        )

    def test_result_envelope_and_gate_revision_are_bound(self):
        envelope = self.catalog["result_envelope"]
        self.assertEqual(envelope["schema_version"], "acs-mcp-result/3")
        self.assertEqual(
            envelope["follow_up_required"], ["rel", "tool", "arguments"]
        )
        self.assertEqual(envelope["metadata_optional"], ["knowledge_hints"])
        self.assertEqual(
            envelope["knowledge_hint_required"],
            ["skill", "topic", "reason", "reference"],
        )
        self.assertEqual(
            self.gates["p2_surface_revision"], self.catalog["surface_revision"]
        )
        self.assertEqual(
            self.gates["gates"]["P2-CONTROL-PARITY"]["requires"],
            ["P2-MANAGEMENT-WORKFLOW"],
        )
        self.assertEqual(
            self.gates["gates"]["P2-CONTROL-PARITY"]["scenarios"],
            ["P2-CONTROL-HANDOFF-ACK"],
        )
        self.assertEqual(
            self.gates["gates"]["P2-REVIEW"]["requires"],
            ["P2-CONTROL-PARITY"],
        )
        for gate in ("P2-MCP-WORKFLOW", "P2-MANAGEMENT-WORKFLOW"):
            scenarios = self.gates["gates"][gate]["scenarios"]
            self.assertEqual(len(scenarios), 12)
            self.assertEqual(len(set(scenarios)), 12)


if __name__ == "__main__":
    unittest.main()
