import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SkillValidationTests(unittest.TestCase):
    def test_validator_passes(self):
        cp = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_skill.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_scaffolds_preserve_agents_admission_contract(self):
        texts = [
            (ROOT / "assets" / "scaffold" / "AGENTS_BLOCK.md").read_text(encoding="utf-8"),
            (ROOT / "assets" / "scaffold" / "workspace" / "AGENTS_BLOCK.md").read_text(encoding="utf-8"),
            (ROOT / "assets" / "scaffold" / "workspace" / "ROUTE_AGENTS.md").read_text(encoding="utf-8"),
        ]
        for text in texts:
            self.assertIn("always-on", text.lower())
            self.assertIn("self-evolution", text)
            self.assertIn("work log", text.lower())
        self.assertIn("startup-critical", texts[1])
        self.assertIn("future Route", texts[2])


if __name__ == "__main__":
    unittest.main()
