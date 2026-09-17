"""Safe development composition tests for the revamped entrypoint."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from compatibility.fixtures import DisposableWorkspace, TEST_ROOT
from revamped.accounts import AccountCompatibilityService
from revamped.extensions import ExtensionService
from revamped.gui import ProfileGUIController
from revamped.launcher import ChromiumLauncher
from revamped.main import compose
from revamped.processes import ChromiumProcessInspector
from revamped.profiles import ProfileService
from revamped.storage import LegacyStateStore, ProfileCatalogStore
from revamped.core import ProfileManagerError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class R9CompositionTests(unittest.TestCase):
    def test_composition_requires_a_root_below_tmp(self):
        with self.assertRaises(ProfileManagerError):
            compose(TEST_ROOT)
        with self.assertRaises(ProfileManagerError):
            compose(Path.cwd())

    def test_composition_wires_explicit_services_below_disposable_root(self):
        with DisposableWorkspace("r9-compose-") as workspace:
            inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
            factory = Mock()
            composition = compose(
                workspace.root,
                process_inspector=inspector,
                process_factory=factory,
            )

            self.assertIsInstance(composition.profile_service, ProfileService)
            self.assertIsInstance(composition.catalog_store, ProfileCatalogStore)
            self.assertIsInstance(composition.legacy_store, LegacyStateStore)
            self.assertIsInstance(composition.extension_service, ExtensionService)
            self.assertIsInstance(composition.account_service, AccountCompatibilityService)
            self.assertIsInstance(composition.launcher, ChromiumLauncher)
            self.assertIsInstance(composition.controller, ProfileGUIController)
            self.assertIs(composition.process_inspector, inspector)
            self.assertFalse(composition.paths.profiles_json.exists())
            self.assertEqual(
                composition.paths.browser_exe,
                PROJECT_ROOT / "browser" / "chrome.exe",
            )
            self.assertEqual(
                composition.paths.extensions_dir,
                PROJECT_ROOT / "extensions",
            )
            self.assertEqual(composition.paths.profiles_dir, workspace.root / "profiles")
            self.assertEqual(composition.paths.data_dir, workspace.root / "data")
            self.assertFalse((workspace.root / "browser").exists())
            self.assertFalse((workspace.root / "extensions").exists())
            self.assertFalse(factory.called)

    def test_explicit_disposable_startup_initializes_only_disposable_state(self):
        with DisposableWorkspace("r9-start-") as workspace:
            result = subprocess.run(
                [
                    sys.executable, "-B", "-m", "revamped.main",
                    "--workspace-root", str(workspace.root),
                    "--no-gui",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("composition ready", result.stdout)
            self.assertIn("No browser process was launched", result.stdout)
            self.assertTrue((workspace.root / "config" / "profiles.json").is_file())
            self.assertTrue((workspace.root / "data" / "Local State").is_file())
            self.assertFalse((workspace.root / "browser" / "chrome.exe").exists())

    def test_no_root_refuses_without_opening_live_state(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "revamped.main"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no stateful development operation was run", result.stderr)


if __name__ == "__main__":
    unittest.main()
