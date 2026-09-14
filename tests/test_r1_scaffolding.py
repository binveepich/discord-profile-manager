"""R1 scaffolding tests; no live application state is opened."""

import importlib
from pathlib import Path
import subprocess
import sys
import unittest

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT, TEST_ROOT


class R1ScaffoldingTests(unittest.TestCase):
    def test_revamped_package_and_modules_import_without_new_files(self):
        before = {
            path.relative_to(PROJECT_ROOT)
            for path in PROJECT_ROOT.rglob("*")
            if path.is_file() and path.is_relative_to(PROJECT_ROOT / "revamped")
        }
        modules = [
            "revamped",
            "revamped.core",
            "revamped.models",
            "revamped.processes",
            "revamped.environment",
            "revamped.proxy",
            "revamped.storage",
            "revamped.profiles",
            "revamped.extensions",
            "revamped.accounts",
            "revamped.launcher",
            "revamped.gui",
        ]
        for name in modules:
            importlib.import_module(name)
        after = {
            path.relative_to(PROJECT_ROOT)
            for path in PROJECT_ROOT.rglob("*")
            if path.is_file() and path.is_relative_to(PROJECT_ROOT / "revamped")
        }
        self.assertEqual(before, after)

    def test_disposable_fixture_is_contained_and_has_no_production_aliases(self):
        with DisposableWorkspace() as workspace:
            self.assertTrue(workspace.root.is_relative_to(TEST_ROOT.resolve()))
            self.assertNotEqual(workspace.root, TEST_ROOT.resolve())
            self.assertFalse(workspace.child("profiles").exists())
            self.assertNotIn("profiles", str(workspace.root).casefold())

    def test_integrity_script_passes(self):
        result = subprocess.run(
            [sys.executable, "-B", "scripts/check_refactor_integrity.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PROTECTED SOURCE INTEGRITY: PASS", result.stdout)

    def test_comparison_harness_reports_unknown_categories_truthfully(self):
        result = subprocess.run(
            [sys.executable, "-B", "scripts/compare_legacy_revamped.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALIDATION: PASS", result.stdout)
        self.assertIn("ENVIRONMENT: PASS", result.stdout)
        self.assertIn("LEGACY/REVAMPED PARITY: NOT IMPLEMENTED", result.stdout)

    def test_revamped_main_refuses_without_stateful_workspace(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "revamped.main"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no stateful development operation was run", result.stderr)


if __name__ == "__main__":
    unittest.main()
