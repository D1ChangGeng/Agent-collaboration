from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# The earlier broad batch is retained, including its two fixture failures and
# explicit interruption. Current focused component/Driver suites cover the
# changed transport stack. This final pass composes affected real Core/TLS and
# every required API; unchanged low-level P2 storage is not repeated here.
targets = ["runtime_tests/" + name + ".py" for name in (
    "test_communication_p1_headless_live", "test_communication_p2_exact_scenarios",
    "test_communication_headless_live", "test_communication_native_source_live_http",
    "test_communication_remote_source_pg", "test_receiver_restore_factory_pg", "test_native_observer_authority",
    "test_receiver_rebind_pg", "test_communication_installed_maintenance")]
targets += ["runtime_tests/test_communication.py::" + name for name in (
    "test_public_work_free_a_b_loop", "test_message_only_never_invokes_and_future_reply_satisfies",
    "test_read_preserves_inbox_and_long_utf8_content_continues")]
targets = list(dict.fromkeys(targets))
assert all((root / p.split("::")[0]).is_file() for p in targets)
env = dict(os.environ, ACS_REVISION_TEST_INSTALL=str(root / ".tmp/development-capabilities-installed"),
           PYTHONPATH=str(root / ".tmp/openapi-check"))
raise SystemExit(subprocess.call([sys.executable, str(root / ".tmp/run_development_capabilities.py"),
    "--name", "development-final-integration-b", "--pg", *targets, "--", "-x", "-o", "faulthandler_timeout=120"], cwd=root, env=env))
