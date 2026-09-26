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
        cls.tools = json.loads(TOOL_CONTRACT.read_text(encoding="utf-8"))
        cls.gates = json.loads(GATE_CONTRACT.read_text(encoding="utf-8"))

    def test_public_surface_is_exact_and_low_level_run_remains_distinct(self):
        self.assertEqual(
            self.tools["ordinary_tools"],
            ["collaboration_apply", "harnesses", "send", "await", "read", "inbox", "cancel"],
        )
        self.assertEqual(self.tools["advanced_tool"], "run")
        self.assertEqual(set(self.tools["ordinary_tools"]), set(self.tools["tools"]))

    def test_send_defaults_and_modes_are_explicit(self):
        self.assertEqual(
            self.tools["defaults"],
            {
                "activation": "invoke",
                "delivery_policy": "queue_until_idle",
                "expect_response": True,
                "response_mode": "async",
                "wait_until": "response_received",
            },
        )
        send = self.tools["tools"]["send"]
        self.assertEqual(send["response_modes"], ["async", "sync"])
        self.assertIn("queue_until_idle", send["delivery_policies"])
        self.assertNotIn("response_mode", send["required"])
        self.assertNotIn("wait_timeout_seconds", send["required"])
        self.assertTrue(
            {"activation", "delivery_policy", "expect_response", "response_mode",
             "wait_until", "wait_timeout_seconds"} <= set(send["optional"])
        )

    def test_common_result_is_self_describing(self):
        required = set(self.tools["common_result"]["required"])
        self.assertTrue({"operation", "delivery", "response", "read", "await", "metadata"} <= required)
        self.assertEqual(
            self.tools["receipt_order"],
            [
                "accepted_by_authority", "target_inbox_committed", "runtime_dispatched",
                "runtime_acknowledged", "response_received",
            ],
        )

    def test_read_contract_covers_result_and_content_views(self):
        read = self.tools["tools"]["read"]
        self.assertEqual(read["result_schema"], "acs-mcp-read-result/1")
        self.assertTrue({"summary", "result", "evidence", "history", "content"} <= set(read["views"]))

    def test_p2_workflow_gate_has_every_adopted_surface_scenario(self):
        scenarios = self.gates["gates"]["P2-MCP-WORKFLOW"]["scenarios"]
        self.assertEqual(self.gates["p2_surface_revision"], self.tools["surface_revision"])
        self.assertEqual(len(scenarios), 12)
        self.assertEqual(len(set(scenarios)), 12)
        self.assertEqual(self.gates["gates"]["P2-REVIEW"]["requires"], ["P2-MCP-WORKFLOW"])


if __name__ == "__main__":
    unittest.main()
