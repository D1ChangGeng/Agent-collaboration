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

    def test_host_retries_failed_children_and_stops_on_owner_success(self):
        probe = Path(self.temp.name) / "retry_probe.cs"
        binary = Path(self.temp.name) / "retry_probe.exe"
        probe.write_text(
            'using System; using System.Reflection;\n'
            'class Probe { static int Main(string[] args) {\n'
            'var type=Assembly.LoadFile(args[0]).GetType("AcsBackgroundHost");\n'
            'var retry=type.GetMethod("RunWithRetry",BindingFlags.Static|BindingFlags.NonPublic);\n'
            'int calls=0,waits=0; int[] exits={9,70,0};\n'
            'object code=retry.Invoke(null,new object[]{new Func<int>(()=>exits[calls++]),new Action(()=>waits++)});\n'
            'if ((int)code!=0 || calls!=3 || waits!=2) return 1;\n'
            'code=retry.Invoke(null,new object[]{new Func<int>(()=>0),new Action(()=>{throw new Exception("unexpected retry");})});\n'
            'return (int)code; }}\n'
        )
        subprocess.run(
            [str(self.compiler), "/nologo", "/target:exe", "/out:" + str(binary), str(probe)],
            check=True, capture_output=True, timeout=20,
        )
        result = subprocess.run(
            [str(binary), str(self.binary.resolve())], capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_upgrade_reuses_recorded_task_name_and_refuses_a_second_name(self):
        shell = shutil.which("powershell.exe")
        if not shell:
            self.skipTest("Windows PowerShell unavailable")
        path = str(ROOT / "scripts/acs_windows_startup.ps1").replace("'", "''")
        command = (
            "$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null; "
            "$ast=[System.Management.Automation.Language.Parser]::ParseFile('"
            + path
            + "',[ref]$tokens,[ref]$errors); "
            "$fn=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
            "-and $node.Name -eq 'Resolve-StartupTaskName'},$true); "
            "Invoke-Expression $fn.Extent.Text; $binding='a'*64; "
            "$owned=[pscustomobject]@{Task='ACS-Ubuntu-Startup-Recovery'}; "
            "if ((Resolve-StartupTaskName '' $binding $owned) -ne $owned.Task) {exit 1}; "
            "if ((Resolve-StartupTaskName '' $binding $null) -ne 'ACS-WSL-aaaaaaaaaaaa-Startup-Recovery') {exit 2}; "
            "$rejected=$false; try {Resolve-StartupTaskName 'ACS-Other-Startup-Recovery' $binding $owned} "
            "catch {$rejected=$true}; if (-not $rejected) {exit 3}"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
