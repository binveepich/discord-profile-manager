"""R2 core/path contract tests with disposable paths only."""

import unittest

from compatibility.fixtures import DisposableWorkspace
from compatibility.legacy_adapter import load_legacy
from revamped.core import (
    ProjectPaths,
    ProfileManagerError,
    checked_path,
    metadata_path_for_profile,
    profile_path_from_metadata,
    validate_candidate_profile_name,
    validate_manager_path,
    validate_profile_id,
)


class CoreContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = load_legacy()

    def test_project_paths_are_explicit_and_do_not_use_cwd(self):
        with DisposableWorkspace() as workspace:
            paths = ProjectPaths(workspace.root / "project with spaces")
            self.assertEqual(paths.browser_exe, paths.root / "browser" / "chrome.exe")
            self.assertEqual(paths.local_state, paths.root / "legacy" / "data" / "Local State")
            self.assertEqual(paths.profiles_json, paths.root / "config" / "profiles.json")

    def test_profile_id_validation_matches_legacy_acceptance(self):
        accepted = ["Default", "Profile 1", "profile_0001", "a.b", "á thử nghiệm"]
        rejected = ["", " ", ".", "..", "CON", "nul.txt", "a/b", "a\\b", "C:relative", "x.", ".deleting-x"]
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(validate_profile_id(value), self.legacy.validate_profile_id(value))
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ProfileManagerError):
                    validate_profile_id(value)
                with self.assertRaises(self.legacy.ProfileManagerError):
                    self.legacy.validate_profile_id(value)

    def test_manager_path_and_candidate_name_contracts(self):
        self.assertEqual(validate_manager_path("profile_0007"), "profile_0007")
        for value in ("../outside", "Profile 1", "profile_x", 1):
            with self.subTest(value=value):
                with self.assertRaises(ProfileManagerError):
                    validate_manager_path(value)
        self.assertTrue(validate_candidate_profile_name("profile_0001"))
        self.assertFalse(validate_candidate_profile_name(".deleting-profile_0001"))

    def test_containment_rejects_escape_and_allows_missing_contained_path(self):
        with DisposableWorkspace() as workspace:
            root = workspace.child("profiles")
            contained = root / "profile_0001" / "Default"
            self.assertEqual(checked_path(contained, root), contained.absolute())
            with self.assertRaises(ProfileManagerError):
                checked_path(root / ".." / "outside", root)

    def test_relative_metadata_paths_round_trip_with_windows_semantics(self):
        with DisposableWorkspace() as workspace:
            paths = ProjectPaths(workspace.root)
            managed = paths.profiles_dir / "profile_0001"
            legacy = paths.data_dir / "Profile 1"
            self.assertEqual(metadata_path_for_profile(managed, paths), "profiles/profile_0001")
            self.assertEqual(metadata_path_for_profile(legacy, paths), "legacy/data/Profile 1")
            self.assertEqual(profile_path_from_metadata("profiles/profile_0001", paths), managed.absolute())
            self.assertEqual(profile_path_from_metadata("legacy\\data\\Profile 1", paths), legacy.absolute())
            for value in ("../outside", "C:/outside", "profiles/../outside", "other/profile"):
                with self.subTest(value=value):
                    with self.assertRaises(ProfileManagerError):
                        profile_path_from_metadata(value, paths)

    def test_linked_path_is_rejected_without_following_it(self):
        with DisposableWorkspace() as workspace:
            root = workspace.child("profiles")
            root.mkdir()
            target = root / "target"
            target.mkdir()
            link = root / "profile_0001"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable in this environment")
            with self.assertRaises(ProfileManagerError):
                checked_path(link, root)


if __name__ == "__main__":
    unittest.main()

