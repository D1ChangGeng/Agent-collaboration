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

    def test_public_surface_uses_concise_action_phrase_names(self):
        ordinary = [
            "setup_collaboration",
            "find_harnesses",
            "send_message",
            "wait_for_response",
            "read_resource",
            "check_inbox",
            "set_notification",
            "cancel_work",
            "stop_attempt",
        ]
        self.assertEqual(self.catalog["naming_convention"], "concise_action_phrase")
        self.assertEqual(
            self.catalog["naming_principles"],
            [
                "intended_action",
                "human_collaboration_phrase",
                "runtime_or_domain_behavior",
                "target_as_argument_when_contract_is_uniform",
                "separate_tool_when_authorization_state_or_result_differs",
            ],
        )
        self.assertEqual(self.catalog["ordinary_tools"], ordinary)
        self.assertEqual(self.catalog["advanced_tools"], ["submit_command"])
        for name in ordinary + ["submit_command"]:
            self.assertIn(len(name.split("_")), (2, 3), name)
        self.assertEqual(
            set(self.catalog["tools"]), set(ordinary) | {"submit_command"}
        )
        self.assertEqual(
            self.catalog["compatibility_aliases"]["run"]["canonical_tool"],
            "submit_command",
        )

    def test_every_tool_exposes_selection_and_result_metadata(self):
        annotation_fields = {
            "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"
        }
        for name, tool in self.catalog["tools"].items():
            with self.subTest(tool=name):
                self.assertTrue(tool["title"])
                self.assertIn("Returns", tool["description"])
                self.assertTrue(tool["selection_guidance"])
                self.assertEqual(set(tool["annotations"]), annotation_fields)
                self.assertTrue(tool["input_schema"]["schema_version"])
                self.assertIn(tool["result_type"], self.catalog["result_types"])

    def test_send_message_defaults_and_modes_are_explicit(self):
        self.assertEqual(
            self.catalog["defaults"],
            {
                "activation": "invoke",
                "delivery_policy": "queue_until_idle",
                "expect_response": True,
                "response_mode": "async",
                "wait_until": "response_received",
            },
        )
        send = self.catalog["tools"]["send_message"]["input_schema"]
        self.assertEqual(send["response_modes"], ["async", "sync"])
        self.assertIn("queue_until_idle", send["delivery_policies"])
        self.assertNotIn("response_mode", send["required"])
        self.assertNotIn("wait_timeout_seconds", send["required"])
        self.assertTrue(
            {
                "activation", "delivery_policy", "expect_response", "response_mode",
                "wait_until", "wait_timeout_seconds",
            }
            <= set(send["optional"])
        )

    def test_results_are_discriminated_and_supply_executable_follow_ups(self):
        envelope = self.catalog["result_envelope"]
        self.assertEqual(envelope["schema_version"], "acs-mcp-result/2")
        self.assertEqual(
            set(envelope["success_required"]),
            {
                "schema_version", "result_type", "ok", "state", "data",
                "follow_ups", "metadata",
            },
        )
        self.assertEqual(
            envelope["follow_up_required"], ["rel", "tool", "arguments"]
        )
        self.assertEqual(
            set(self.catalog["result_types"]["message_submission"]),
            {"operation", "message", "delivery", "response", "notification"},
        )
        self.assertEqual(
            self.catalog["receipt_order"],
            [
                "accepted_by_authority", "target_inbox_committed",
                "runtime_dispatched", "runtime_acknowledged", "response_received",
            ],
        )

    def test_read_and_wait_contracts_cover_continuation(self):
        read_tool = self.catalog["tools"]["read_resource"]
        read = read_tool["input_schema"]
        self.assertTrue(
            {"summary", "result", "evidence", "history", "content"}
            <= set(read["views"])
        )
        await_tool = self.catalog["tools"]["wait_for_response"]
        await_schema = await_tool["input_schema"]
        self.assertEqual(await_schema["modes"], ["any", "all"])
        self.assertFalse(read_tool["annotations"]["readOnlyHint"])
        self.assertFalse(await_tool["annotations"]["readOnlyHint"])
        self.assertTrue(
            self.catalog["tools"]["check_inbox"]["annotations"]["readOnlyHint"]
        )
        self.assertEqual(
            self.catalog["tools"]["check_inbox"]["result_type"], "inbox_page"
        )

    def test_parameterized_tools_and_split_control_boundaries_are_explicit(self):
        self.assertEqual(
            self.catalog["tools"]["read_resource"]["input_schema"]["required"],
            ["handle"],
        )
        self.assertIn(
            "handles",
            self.catalog["tools"]["wait_for_response"]["input_schema"]["required"],
        )
        self.assertIn(
            "response_handle",
            self.catalog["tools"]["set_notification"]["input_schema"]["required"],
        )
        self.assertNotEqual(
            self.catalog["tools"]["cancel_work"]["result_type"],
            self.catalog["tools"]["stop_attempt"]["result_type"],
        )

    def test_p2_workflow_gate_binds_the_surface_revision(self):
        scenarios = self.gates["gates"]["P2-MCP-WORKFLOW"]["scenarios"]
        self.assertEqual(self.gates["p2_surface_revision"], self.catalog["surface_revision"])
        self.assertEqual(len(scenarios), 12)
        self.assertEqual(len(set(scenarios)), 12)
        self.assertEqual(
            self.gates["gates"]["P2-REVIEW"]["requires"], ["P2-MCP-WORKFLOW"]
        )


if __name__ == "__main__":
    unittest.main()
