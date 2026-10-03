from __future__ import annotations

import threading
import unittest
from unittest import mock

from test_release_tools import load


class SetupPerformanceTests(unittest.TestCase):
    def test_static_probes_overlap_and_skip_unselected_harness(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        barrier = threading.Barrier(4)
        names = []
        def probe(name, *_args):
            names.append(name)
            if name in {"git", "uv", "docker", "codex"}:
                barrier.wait(timeout=2)
            return {"available": True, "detail": "ready"}
        with mock.patch.object(doctor, "command_version", side_effect=probe):
            result = doctor.inspect(harnesses=["codex"], deep=False)
        self.assertEqual(set(result["tools"]), {"git", "uv", "docker", "codex"})
        self.assertNotIn("opencode", names)
        self.assertEqual(result["validation_scope"], "machine")

    def test_post_install_reuses_static_probes_and_still_checks_runtime(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        snapshot = {name: {"available": True, "detail": "observed"} for name in ("git", "uv", "docker")}
        with mock.patch.object(doctor, "command_version", return_value={"available": True}) as probe:
            result = doctor.inspect(harnesses=[], deep=False, tools_snapshot=snapshot)
        self.assertFalse(any(call.args[0] in snapshot for call in probe.call_args_list))
        self.assertTrue(result["tool_probes_reused"])
