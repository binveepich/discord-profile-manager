"""Disposable-root tests for the revamped profile lifecycle boundary."""

import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from revamped.core import ProfileManagerError, ProfileNotFoundError, ProjectPaths
from revamped.profiles import ProfileService
from revamped.storage import LegacyStateStore
from tests.compatibility.fixtures import DisposableWorkspace


class NoProcesses:
    def using_directory(self, directory, exact=False):
        return False


class BlockingProcesses:
    def __init__(self, blocked):
        self.blocked = Path(blocked).absolute()

    def using_directory(self, directory, exact=False):
        return Path(directory).absolute() == self.blocked


class ProfileLifecycleTests(unittest.TestCase):
    def make_service(self, workspace, *, process_inspector=None, clock=None):
        paths = ProjectPaths(workspace.root)
        service = ProfileService(
            paths,
            process_inspector=process_inspector or NoProcesses(),
            clock=clock,
        )
        return paths, service

    def seed_legacy_profile(self, workspace, profile_id="Profile 1", display_name="Legacy"): 
        paths = ProjectPaths(workspace.root)
        store = LegacyStateStore(paths)
        state = store.load()
        store.save(state)
        profile_dir = paths.data_dir / profile_id / "Default"
        profile_dir.mkdir(parents=True)
        (profile_dir / "Preferences").write_text(
            json.dumps({"profile": {"name": display_name}}), encoding="utf-8"
        )
        state = store.load()
        state["profile"]["info_cache"][profile_id] = {
            "name": display_name,
            "created": 100,
        }
        store.save(state)
        return paths

    def test_create_survives_restart_and_publishes_isolated_structure(self):
        with DisposableWorkspace("r7-create-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("First")

            profile_dir = paths.profiles_dir / profile_id
            self.assertEqual(profile_id, "profile_0001")
            self.assertTrue((profile_dir / "Default" / "Preferences").is_file())
            self.assertTrue((profile_dir / "Unpacked Extensions").is_dir())
            record = service.get_profile_record(profile_id)
            self.assertEqual(record["display_name"], "First")
            self.assertEqual(record["profile_directory"], f"profiles/{profile_id}")

            restarted = ProfileService(paths, process_inspector=NoProcesses())
            self.assertEqual(restarted.get_profiles(), [(profile_id, "First")])
            self.assertEqual(restarted.require_profile_dir(profile_id), profile_dir)

    def test_failed_create_preserves_path_and_does_not_reuse_id(self):
        with DisposableWorkspace("r7-create-failure-") as workspace:
            paths, service = self.make_service(workspace)
            service.initialize_metadata()
            with patch.object(service.catalog_store, "save", side_effect=OSError("catalog unavailable")):
                with self.assertRaises(OSError):
                    service.create_profile("Unpublished")

            first_dir = paths.profiles_dir / "profile_0001"
            self.assertTrue((first_dir / "Default" / "Preferences").is_file())
            self.assertEqual(service.get_profiles(), [])
            self.assertEqual(service.create_profile("Second"), "profile_0002")
            self.assertTrue(first_dir.is_dir())

    def test_rename_changes_metadata_only(self):
        with DisposableWorkspace("r7-rename-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Before")
            profile_dir = paths.profiles_dir / profile_id

            service.rename_profile(profile_id, "After")

            self.assertTrue(profile_dir.is_dir())
            self.assertEqual(service.get_profile_record(profile_id)["display_name"], "After")

    def test_delete_success_stages_then_removes_profile_and_metadata(self):
        with DisposableWorkspace("r7-delete-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Delete me")
            profile_dir = paths.profiles_dir / profile_id

            service.delete_profile(profile_id)

            self.assertFalse(profile_dir.exists())
            self.assertFalse(any(paths.profiles_dir.glob(f".deleting-{profile_id}-*")))
            with self.assertRaises(ProfileNotFoundError):
                service.get_profile_record(profile_id)

    def test_delete_publication_failure_restores_original_path_and_metadata(self):
        with DisposableWorkspace("r7-delete-rollback-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Keep me")
            profile_dir = paths.profiles_dir / profile_id
            original_catalog = paths.profiles_json.read_bytes()

            with patch.object(service.catalog_store, "save", side_effect=OSError("catalog unavailable")):
                with self.assertRaises(OSError):
                    service.delete_profile(profile_id)

            self.assertTrue(profile_dir.is_dir())
            self.assertFalse(any(paths.profiles_dir.glob(f".deleting-{profile_id}-*")))
            self.assertEqual(paths.profiles_json.read_bytes(), original_catalog)
            self.assertEqual(service.get_profile_record(profile_id)["display_name"], "Keep me")

    def test_delete_cleanup_failure_preserves_staging_without_retry(self):
        with DisposableWorkspace("r7-delete-cleanup-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Keep staging")

            with patch("revamped.profiles.shutil.rmtree", side_effect=OSError("locked")):
                with self.assertRaises(ProfileManagerError):
                    service.delete_profile(profile_id)

            pending = list(paths.profiles_dir.glob(f".deleting-{profile_id}-*"))
            self.assertEqual(len(pending), 1)
            self.assertFalse((paths.profiles_dir / profile_id).exists())
            self.assertEqual(service.get_profiles(), [])

    def test_delete_and_migrate_reject_running_data(self):
        with DisposableWorkspace("r7-running-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Running")
            profile_dir = paths.profiles_dir / profile_id
            blocked = ProfileService(paths, process_inspector=BlockingProcesses(profile_dir))

            with self.assertRaises(ProfileManagerError):
                blocked.delete_profile(profile_id)
            self.assertTrue(profile_dir.is_dir())

        with DisposableWorkspace("r7-running-migrate-") as workspace:
            paths = self.seed_legacy_profile(workspace)
            service = ProfileService(paths, process_inspector=BlockingProcesses(paths.data_dir / "Profile 1"))
            with self.assertRaises(ProfileManagerError):
                service.migrate_profile("Profile 1")
            self.assertTrue((paths.data_dir / "Profile 1").is_dir())

    def test_migration_is_copy_only_and_publishes_after_copy(self):
        with DisposableWorkspace("r7-migrate-") as workspace:
            paths = self.seed_legacy_profile(workspace)
            service = ProfileService(paths, process_inspector=NoProcesses())
            source = paths.data_dir / "Profile 1"

            managed_id = service.migrate_profile("Profile 1")

            destination = paths.profiles_dir / managed_id
            self.assertEqual(managed_id, "profile_0001")
            self.assertTrue(source.is_dir())
            self.assertTrue((source / "Default" / "Preferences").is_file())
            self.assertTrue((destination / "Default" / "Preferences").is_file())
            self.assertEqual(
                service.get_profile_record("Profile 1")["profile_directory"],
                f"profiles/{managed_id}",
            )

    def test_migration_copy_failure_leaves_source_and_metadata_unchanged(self):
        with DisposableWorkspace("r7-migrate-failure-") as workspace:
            paths = self.seed_legacy_profile(workspace)
            service = ProfileService(paths, process_inspector=NoProcesses())
            original_record = service.get_profile_record("Profile 1")
            source = paths.data_dir / "Profile 1"

            with patch("revamped.profiles.shutil.copytree", side_effect=OSError("copy failed")):
                with self.assertRaises(ProfileManagerError):
                    service.migrate_profile("Profile 1")

            self.assertTrue(source.is_dir())
            self.assertEqual(service.get_profile_record("Profile 1"), original_record)
            self.assertTrue(paths.profiles_dir.is_dir())
            self.assertFalse((paths.profiles_dir / "profile_0001").exists())

    def test_migration_publication_failure_keeps_source_and_marks_copy_unpublished(self):
        with DisposableWorkspace("r7-migrate-publish-failure-") as workspace:
            paths = self.seed_legacy_profile(workspace)
            service = ProfileService(paths, process_inspector=NoProcesses())
            source = paths.data_dir / "Profile 1"
            service.get_profile_record("Profile 1")

            with patch.object(service.catalog_store, "save", side_effect=OSError("catalog unavailable")):
                with self.assertRaises(ProfileManagerError):
                    service.migrate_profile("Profile 1")

            destination = paths.profiles_dir / "profile_0001"
            self.assertTrue(source.is_dir())
            self.assertTrue(destination.is_dir())
            self.assertEqual(service.get_profiles(), [("Profile 1", "Legacy")])

    def test_missing_profile_is_not_recreated(self):
        with DisposableWorkspace("r7-missing-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Missing")
            profile_dir = paths.profiles_dir / profile_id
            shutil.rmtree(profile_dir)

            with self.assertRaises(ProfileNotFoundError):
                service.require_profile_dir(profile_id)
            self.assertFalse(profile_dir.exists())

    def test_malformed_catalog_is_preserved(self):
        with DisposableWorkspace("r7-malformed-") as workspace:
            paths, service = self.make_service(workspace)
            service.create_profile("Malformed")
            raw = b'{"version": 1, "profiles": [}'
            paths.profiles_json.write_bytes(raw)

            with self.assertRaises(ProfileManagerError):
                service.get_profiles()
            self.assertEqual(paths.profiles_json.read_bytes(), raw)

    def test_browser_layout_validation_rejects_flat_shared_root_data(self):
        with DisposableWorkspace("r7-layout-") as workspace:
            paths, service = self.make_service(workspace)
            profile_id = service.create_profile("Layout")
            profile_dir = paths.profiles_dir / profile_id
            (profile_dir / "Cookies").write_bytes(b"synthetic")

            with self.assertRaises(ProfileManagerError):
                service.get_browser_profile_dir(profile_id)

    def test_last_opened_is_updated_by_successful_launch_equivalent_operation(self):
        with DisposableWorkspace("r7-opened-") as workspace:
            from datetime import datetime, timezone

            clock = lambda: datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
            _, service = self.make_service(workspace, clock=clock)
            profile_id = service.create_profile("Opened")
            self.assertIsNone(service.get_profile_record(profile_id)["last_opened_at"])

            service.mark_profile_opened(profile_id)

            self.assertEqual(
                service.get_profile_record(profile_id)["last_opened_at"],
                "2026-09-15T12:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
