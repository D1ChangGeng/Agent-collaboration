"""Native Windows background host and installation entry validation."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Native Windows startup installation")
class WindowsStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = Path(cls.temp.name) / "acs_background_host.exe"
        cls.compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        if not cls.compiler.exists():
            raise unittest.SkipTest("Windows Framework compiler unavailable")
        subprocess.run(
            [
                str(cls.compiler),
                "/nologo",
                "/target:winexe",
                "/platform:x64",
                "/out:" + str(cls.binary),
                str(ROOT / "assets/windows/acs_background_host.cs"),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )

    def test_host_has_gui_subsystem(self):
        data = self.binary.read_bytes()
        header = struct.unpack_from("<I", data, 60)[0]
        self.assertEqual(data[header : header + 4], b"PE\0\0")
        self.assertEqual(struct.unpack_from("<H", data, header + 24 + 68)[0], 2)

    def test_host_only_admits_the_system_wsl_executable(self):
        result = subprocess.run(
            [str(self.binary), "cmd.exe", "/c", "echo fixture"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_powershell_installer_parses_with_native_windows_parser(self):
        shell = shutil.which("powershell.exe")
        if not shell:
            self.skipTest("Windows PowerShell unavailable")
        path = str(ROOT / "scripts/acs_windows_startup.ps1").replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('"
            + path
            + "',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { Write-Error 'Windows startup syntax validation failed'; exit 1 }"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
