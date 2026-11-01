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
        self.assertIn("global", groups)
        self.assertIn("communication", groups)
        names = [name for group in groups.values() for name in group]
        self.assertEqual(len(names), len(set(names)))
        aliases = self.catalog["compatibility_aliases"]
        self.assertEqual(aliases, {"configure_project": "configure_root"})
        self.assertFalse(set(names).intersection(aliases))
        self.assertEqual(set(names) | set(aliases), set(self.catalog["tools"]))
        self.assertTrue(set(aliases.values()) <= set(names))
        from runtime.project_service import ProjectService
        self.assertTrue((set(aliases) | set(aliases.values())) <= ProjectService.IMPLEMENTED)
        self.assertIn("configure_root", names)
        self.assertIn("configure_team", names)
        self.assertIn("list_harnesses", names)
        self.assertNotIn("setup_collaboration", names)
        self.assertNotIn("find_harnesses", names)
        from runtime.communication_tools import TASK_TOOLS
        self.assertFalse(set(names).intersection(TASK_TOOLS))
        self.assertIn("list_messages", names)
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

    def test_first_entry_result_contract_exposes_actor_identity_and_current_context(self):
        profile = set(self.catalog["result_types"]["profile_snapshot"])
        self.assertTrue({"subject", "tenant_id", "profile", "actor", "organization_model"} <= profile)
        self.assertFalse(profile.intersection({"tenant", "profiles", "connections"}))
        context = set(self.catalog["result_types"]["project_context"])
        self.assertTrue({"project_id", "root_handle", "actor_binding", "communication_address"} <= context)
        self.assertFalse(context.intersection({"project", "active_work_summary"}))

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
        self.assertEqual(required, {"project_id", "members"})
        self.assertIn("expected_revision", configure["input_schema"]["optional"])
        self.assertIn("scope_handle", configure["input_schema"]["optional"])
        member = configure["input_schema"]["json_schema"]["properties"]["members"]["items"]
        self.assertIn("if_unchanged", member["properties"])

    def test_read_and_message_consumption_are_separate(self):
        resource = self.catalog["tools"]["read_resource"]
        message = self.catalog["tools"]["read_message"]
        self.assertTrue(resource["annotations"]["readOnlyHint"])
        self.assertTrue(message["annotations"]["readOnlyHint"])
        self.assertNotIn("consume", resource["input_schema"]["optional"])
        self.assertNotIn("consume", message["input_schema"]["optional"])
        self.assertFalse(self.catalog["defaults"]["read_consumes"])
        self.assertEqual(resource["input_schema"]["json_schema"]["properties"]["view"]["enum"],
                         ["summary", "detail", "content"])
        self.assertNotIn("WorkItem", resource["description"])
        self.assertNotIn("active work", self.catalog["tools"]["load_project"]["description"])

    def test_send_wait_and_subscription_defaults_are_explicit(self):
        defaults = self.catalog["defaults"]
        self.assertEqual(defaults["response_mode"], "async")
        self.assertEqual(defaults["delivery_policy"], "queue_until_idle")
        send = self.catalog["tools"]["send_message"]["input_schema"]
        self.assertIn("response_mode", send["optional"])
        self.assertNotIn("response_mode", send["required"])
        self.assertEqual(send["required"], ["project_id", "to", "content"])
        self.assertEqual(send["json_schema"]["properties"]["response_mode"]["enum"], ["async", "sync"])
        self.assertEqual(
            self.catalog["tools"]["wait_for_response"]["input_schema"]["json_schema"]["properties"]["mode"]["enum"],
            ["any", "all"],
        )
        self.assertNotIn("work_handle", send["json_schema"]["properties"])

    def test_profiles_limit_tool_discovery(self):
        profiles = self.catalog["profiles"]
        self.assertIn("load_project", profiles["root_manager"])
        self.assertIn("send_message", profiles["reviewer"])
        self.assertNotIn("accept_work", profiles["reviewer"])
        self.assertIn("apply_patch", profiles["engineer"])
        self.assertNotIn("configure_team", profiles["engineer"])
        self.assertNotIn("configure_team", profiles["reviewer"])

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
        # Historical Gates retain the surface they measured. New communication
        # semantics require new evidence, never rewriting a passed old Gate.
        self.assertEqual(self.catalog["surface_revision"], "acs-communication/1")
        self.assertTrue(self.gates["p2_surface_revision"].startswith("acs-p2-mcp-workflow/"))
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
