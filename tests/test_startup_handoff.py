"""Real owner lock handoff during Windows task replacement."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux recovery lock ownership")
class StartupHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        private = self.root / "private"
        private.mkdir()
        (self.root / "state.json").write_text(
            json.dumps({"runtime_config_ref": str(private / "surface.json")})
        )
        self.script = self.root / "legacy.py"
        self.script.write_text(
            "import fcntl,time\nfrom pathlib import Path\nf=open("
            + repr(str(private / "login-recovery.lock"))
            + ",'w')\nfcntl.flock(f,fcntl.LOCK_EX)\nPath("
            + repr(str(self.root / "ready"))
            + ").write_text('ready')\ntime.sleep(30)\n"
        )
        self.process = subprocess.Popen([sys.executable, str(self.script)])
        self.addCleanup(self.stop)
        end = time.monotonic() + 3
        while not (self.root / "ready").exists() and time.monotonic() < end:
            time.sleep(0.02)
        self.assertTrue((self.root / "ready").exists())
        source = (ROOT / "scripts/acs_windows_startup.ps1").read_text()
        match = re.search(
            r"function Stop-OwnedMaintainer.*?\$code = @'\n(.*?)\n'@", source, re.DOTALL
        )
        self.assertIsNotNone(match)
        self.code = match.group(1)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=4)

    def test_exact_legacy_owner_lock_is_released_for_replacement(self):
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                "import os\nos.kill=lambda *a: (_ for _ in ()).throw(AssertionError('numeric signal used'))\n"
                + self.code,
                str(self.root),
                str(self.script),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            env=dict(os.environ, PYTHONOPTIMIZE="1"),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.process.wait(timeout=3)
        self.assertIsNotNone(self.process.returncode)

    def test_unknown_lock_holder_is_kept_running(self):
        result = subprocess.run(
            ["/usr/bin/python3", "-c", self.code, str(self.root), str(self.root / "different.py")],
            capture_output=True,
            text=True,
            timeout=8,
            env=dict(os.environ, PYTHONOPTIMIZE="1"),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()
