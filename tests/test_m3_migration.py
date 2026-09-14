"""M3 profile-root migration tests using disposable synthetic data."""

import json
import unittest
from unittest.mock import patch

import test_m1_runtime as m1


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_profiles = m1.RuntimeTests.make_profiles
    make_launch_profile = m1.RuntimeTests.make_launch_profile
    make_runtime = m1.RuntimeTests.make_runtime

    def write_registry(self, raw):
        self.data.mkdir(parents=True, exist_ok=True)
        self.manager.LOCAL_STATE.write_bytes(raw)

    def test_new_profiles_use_managed_root_and_marker(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Managed")

        self.assertEqual(profile_id, "profile_0001")
        self.assertTrue((self.profiles / profile_id / "Default" / "Preferences").is_file())
        self.assertFalse((self.data / profile_id).exists())
        info = profiles.local_state.load()["profile"]["info_cache"][profile_id]
        self.assertEqual(info["manager_path"], profile_id)

    def test_new_profile_launch_uses_managed_root(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Managed")

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        self.assertEqual(self.popen.call_args.args[0][1], f"--user-data-dir={self.profiles / profile_id}")

    def test_managed_root_with_spaces_and_unicode_is_contained(self):
        project = self.work / "Project with spaces Thử nghiệm"
        data = project / "legacy" / "data"
        managed = project / "profiles"
        with patch.object(self.manager, "DATA_DIR", data), \
                patch.object(self.manager, "LOCAL_STATE", data / "Local State"), \
                patch.object(self.manager, "PROFILES_DIR", managed):
            profiles = self.manager.ProfileManager()
            profile_id = profiles.create_profile("Spaced")
            path = profiles.get_profile_dir(profile_id)

        self.assertEqual(path, managed / "profile_0001")
        self.assertTrue((path / "Default" / "Preferences").is_file())

    def test_legacy_profile_is_resolved_and_migrated_without_destroying_source(self):
        source = self.make_launch_profile("Profile 1")
        marker = source / "Default" / "session.fixture"
        marker.write_bytes(b"legacy session")
        before_source = {
            path.relative_to(source): path.read_bytes()
            for path in source.rglob("*") if path.is_file()
        }
        profiles = self.manager.ProfileManager()

        migrated_id = profiles.migrate_profile("Profile 1")
        destination = self.profiles / migrated_id

        self.assertEqual(migrated_id, "profile_0001")
        self.assertTrue(destination.is_dir())
        self.assertEqual(
            {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()},
            before_source,
        )
        self.assertEqual((destination / "Default" / "session.fixture").read_bytes(), b"legacy session")
        self.assertEqual(profiles.get_profile_dir("Profile 1"), destination)
        self.assertEqual(profiles.migrate_profile("Profile 1"), migrated_id)
        self.assertFalse((self.profiles / "profile_0002").exists())
        self.assertEqual(profiles.local_state.load()["profile"]["info_cache"]["Profile 1"]["manager_path"], migrated_id)

    def test_legacy_profiles_continue_to_use_legacy_root_until_migrated(self):
        source = self.make_launch_profile("Profile 1")
        profiles = self.manager.ProfileManager()

        self.assertEqual(profiles.get_profile_dir("Profile 1"), source)
        self.assertFalse((self.profiles / "Profile 1").exists())

    def test_new_id_avoids_existing_managed_directory(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        orphan = self.profiles / "profile_0001"
        orphan.mkdir(parents=True)
        (orphan / "keep.fixture").write_bytes(b"orphan")

        profile_id = self.manager.ProfileManager().create_profile("Next")

        self.assertEqual(profile_id, "profile_0002")
        self.assertEqual((orphan / "keep.fixture").read_bytes(), b"orphan")

    def test_new_id_avoids_legacy_directory_using_managed_name(self):
        self.write_registry(b'{"profile":{"info_cache":{}}}')
        orphan = self.data / "profile_0001"
        orphan.mkdir(parents=True)
        (orphan / "keep.fixture").write_bytes(b"legacy orphan")

        profile_id = self.manager.ProfileManager().create_profile("Next")

        self.assertEqual(profile_id, "profile_0002")
        self.assertEqual((orphan / "keep.fixture").read_bytes(), b"legacy orphan")

    def test_duplicate_managed_paths_are_rejected(self):
        raw = json.dumps({
            "profile": {"info_cache": {
                "Profile 1": {"name": "A", "manager_path": "profile_0001"},
                "Profile 2": {"name": "B", "manager_path": "PROFILE_0001"},
            }}
        }).encode()
        self.write_registry(raw)

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profiles()
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), raw)

    def test_copy_failure_leaves_legacy_source_and_metadata_unchanged(self):
        source = self.make_launch_profile("Profile 1")
        original_metadata = self.manager.LOCAL_STATE.read_bytes()
        profiles = self.manager.ProfileManager()
        with patch.object(self.manager.shutil, "copytree", side_effect=OSError("synthetic copy failure")):
            with self.assertRaisesRegex(self.manager.ProfileManagerError, "source was left untouched"):
                profiles.migrate_profile("Profile 1")

        self.assertTrue(source.is_dir())
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original_metadata)
        self.assertNotIn("manager_path", profiles.local_state.load()["profile"]["info_cache"]["Profile 1"])

    def test_metadata_failure_keeps_both_copies_and_does_not_publish_marker(self):
        source = self.make_launch_profile("Profile 1")
        profiles = self.manager.ProfileManager()
        with patch.object(profiles.local_state, "save", side_effect=self.manager.ProfileManagerError("synthetic save failure")):
            with self.assertRaisesRegex(self.manager.ProfileManagerError, "metadata could not be updated"):
                profiles.migrate_profile("Profile 1")

        destination = self.profiles / "profile_0001"
        self.assertTrue(source.is_dir())
        self.assertTrue(destination.is_dir())
        self.assertNotIn("manager_path", profiles.local_state.load()["profile"]["info_cache"]["Profile 1"])

    def test_malformed_migration_marker_is_rejected_without_path_fallback(self):
        raw = json.dumps({
            "profile": {"info_cache": {"Profile 1": {"name": "Legacy", "manager_path": "..\\outside"}}}
        }).encode()
        self.write_registry(raw)
        (self.data / "Profile 1").mkdir()

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().get_profile_dir("Profile 1")
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), raw)

    def test_missing_registry_with_managed_data_is_not_reset(self):
        profile = self.profiles / "profile_0001"
        profile.mkdir(parents=True)
        (profile / "keep.fixture").write_bytes(b"preserve")

        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ProfileManager().create_profile("New")

        self.assertFalse(self.manager.LOCAL_STATE.exists())
        self.assertEqual((profile / "keep.fixture").read_bytes(), b"preserve")

    def test_deleting_migrated_profile_removes_managed_copy_but_not_legacy_source(self):
        source = self.make_launch_profile("Profile 1")
        profiles = self.manager.ProfileManager()
        migrated_id = profiles.migrate_profile("Profile 1")
        destination = self.profiles / migrated_id

        profiles.delete_profile("Profile 1")

        self.assertFalse(destination.exists())
        self.assertTrue(source.is_dir())
        self.assertEqual(profiles.get_profiles(), [])
        self.assertFalse(any(self.profiles.glob(".deleting-*")))


if __name__ == "__main__":
    unittest.main()
