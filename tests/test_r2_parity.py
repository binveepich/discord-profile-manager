"""R2 deterministic parity checks over synthetic inputs."""

import subprocess
import sys
import unittest


class R2ParityTests(unittest.TestCase):
    def test_compare_script_reports_implemented_core_categories_only(self):
        result = subprocess.run(
            [sys.executable, "-B", "scripts/compare_legacy_revamped.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALIDATION: PASS", result.stdout)
        self.assertIn("PATH POLICY: PASS", result.stdout)
        self.assertIn("ENVIRONMENT: PASS", result.stdout)
        self.assertIn("LEGACY/REVAMPED PARITY: NOT IMPLEMENTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
