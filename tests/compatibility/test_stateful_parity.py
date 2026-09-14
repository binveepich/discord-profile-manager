"""Disposable stateful parity scenarios using explicit adapters."""

from pathlib import Path
import unittest
from unittest.mock import patch

from .fixtures import DisposableWorkspace
from .legacy_adapter import load_legacy
from .revamped_adapter import load_revamped


class StatefulCompatibilityTests(unittest.TestCase):
    def test_create_rename_and_copy_only_migration_match(self):
        with DisposableWorkspace("compat-legacy-") as legacy_workspace, DisposableWorkspace(
            "compat-revamped-"
        ) as revamped_workspace:
            legacy = load_legacy()
            legacy_paths = self._configure_legacy(legacy, legacy_workspace.root)
            with patch.object(legacy.psutil, "process_iter", return_value=[]):
                manager = legacy.ProfileManager()
                profile_id = manager.create_profile("Parity")
                original_path = manager.get_profile_dir(profile_id)
                manager.rename_profile(profile_id, "Renamed")
                legacy_result = (
                    profile_id,
                    manager.get_profiles(),
                    original_path.relative_to(legacy_paths.root).as_posix(),
                )

            revamped = load_revamped()
            revamped_paths = revamped["core"].ProjectPaths(revamped_workspace.root)
            service = revamped["profiles"].ProfileService(
                revamped_paths,
                process_inspector=revamped["profiles"].ChromiumProcessInspector(
                    process_iter=lambda *_: []
                ),
            )
            profile_id = service.create_profile("Parity")
            original_path = service.get_profile_dir(profile_id)
            service.rename_profile(profile_id, "Renamed")
            revamped_result = (
                profile_id,
                service.get_profiles(),
                original_path.relative_to(revamped_paths.root).as_posix(),
            )

            self.assertEqual(legacy_result, revamped_result)

    @staticmethod
    def _configure_legacy(legacy, root):
        paths = load_revamped()["core"].ProjectPaths(root)
        for attribute, value in {
            "PROJECT_ROOT": paths.root,
            "BROWSER_EXE": paths.browser_exe,
            "DATA_DIR": paths.data_dir,
            "PROFILES_DIR": paths.profiles_dir,
            "CONFIG_DIR": paths.config_dir,
            "PROFILES_JSON": paths.profiles_json,
            "LOCAL_STATE": paths.local_state,
            "LOG_DIR": paths.legacy_log_dir,
            "EXTENSIONS_DIR": paths.extensions_dir,
            "EXT_DIR": paths.autofill_extension_dir,
        }.items():
            setattr(legacy, attribute, value)
        return paths


if __name__ == "__main__":
    unittest.main()
