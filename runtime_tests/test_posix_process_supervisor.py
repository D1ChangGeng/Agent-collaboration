"""Actual owned process groups keep normal machine execution available."""
import os
import sys

import pytest

from runtime.posix_process_supervisor import PosixProcessSupervisor

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process identities")


def test_owned_process_group_is_stopped_without_touching_other_processes(tmp_path):
    supervisor = PosixProcessSupervisor(termination_timeout=1)
    own = supervisor.launch([sys.executable, "-c", "import time; time.sleep(60)"],
                            cwd=str(tmp_path), env=dict(os.environ), label="owned-test")
    other = supervisor.launch([sys.executable, "-c", "import time; time.sleep(60)"],
                              cwd=str(tmp_path), env=dict(os.environ), label="other-test")
    try:
        view = supervisor.inspect(own)
        assert view["scope"] == "owned_process_group" and view["subtree_containment"] is False
        assert view["root_pid"] == own.process.pid and not view["root_exited"]
        assert own.process.pid in view["remaining_pids"] == view["members"]
        assert supervisor.terminate_tree(own)["stopped"]
        assert supervisor.inspect(other)["alive"]
    finally:
        supervisor.close()
