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


if __name__ == "__main__":
    unittest.main()
