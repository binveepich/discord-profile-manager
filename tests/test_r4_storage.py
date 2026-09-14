"""R4 storage boundary and fault-injection tests using disposable roots."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ProfileManagerError
from revamped.models import new_profile_record
from revamped.storage import (
    LegacyStateStore,
    MirrorCoordinator,
    ProfileCatalogStore,
    empty_catalog,
)
from revamped.core import ProjectPaths


class StorageBoundaryTests(unittest.TestCase):
    def make_bundle(self):
        self.workspace = DisposableWorkspace("r4-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.paths = ProjectPaths(self.workspace.root)
        return ProfileCatalogStore(self.paths), LegacyStateStore(self.paths)

    def make_catalog(self, paths):
        record = new_profile_record(
            "profile_0001", "One", paths.profiles_dir / "profile_0001", paths,
            created_at="2026-01-01T00:00:00Z",
        ).to_mapping()
        return {"version": 1, "profiles": [record]}

    def test_catalog_missing_is_uninitialized_and_round_trips_safe_unknown_fields(self):
        catalog_store, _ = self.make_bundle()
        self.assertIsNone(catalog_store.load())
        catalog = self.make_catalog(self.paths)
        catalog["profiles"][0]["ui_color"] = "blue"
        catalog_store.save(catalog)
        loaded = catalog_store.load()
        self.assertEqual(loaded["profiles"][0]["ui_color"], "blue")

    def test_catalog_rejects_sensitive_and_duplicate_metadata_without_rewrite(self):
        catalog_store, _ = self.make_bundle()
        catalog = self.make_catalog(self.paths)
        catalog_store.save(catalog)
        original = catalog_store.path.read_bytes()
        sensitive = self.make_catalog(self.paths)
        sensitive["profiles"][0]["password"] = "synthetic-password"
        with self.assertRaises(ProfileManagerError):
            catalog_store.save(sensitive)
        self.assertEqual(catalog_store.path.read_bytes(), original)
        duplicate = b'{"version":1,"profiles":[],"profiles":[]}'
        catalog_store.path.write_bytes(duplicate)
        with self.assertRaises(ProfileManagerError):
            catalog_store.load()
        self.assertEqual(catalog_store.path.read_bytes(), duplicate)

    def test_catalog_stale_write_is_rejected(self):
        first, _ = self.make_bundle()
        catalog = empty_catalog()
        first.save(catalog)
        second = ProfileCatalogStore(self.paths)
        stale = first.load()
        second.load()
        latest = empty_catalog()
        latest["ui_state"] = "synthetic"
        second.save(latest)
        stale["new_field"] = "stale"
        with self.assertRaises(ProfileManagerError):
            first.save(stale)
        self.assertEqual(second.load()["ui_state"], "synthetic")

    def test_catalog_atomic_replace_failure_preserves_original_and_temp_cleanup(self):
        catalog_store, _ = self.make_bundle()
        catalog = self.make_catalog(self.paths)
        catalog_store.save(catalog)
        original = catalog_store.path.read_bytes()
        changed = json.loads(original.decode("utf-8"))
        changed["profiles"][0]["display_name"] = "Changed"
        with patch.object(Path, "replace", side_effect=PermissionError("synthetic denial")):
            with self.assertRaises(ProfileManagerError):
                catalog_store.save(changed)
        self.assertEqual(catalog_store.path.read_bytes(), original)
        self.assertEqual(list(catalog_store.path.parent.glob(".profiles-*.tmp")), [])

    def test_legacy_state_uses_operation_lock_and_preserves_unknown_fields(self):
        _, legacy = self.make_bundle()
        state = legacy.load()
        state["unknown_browser_state"] = {"fixture": True}
        legacy.save(state)
        with legacy.operation():
            with self.assertRaises(ProfileManagerError):
                with legacy.operation():
                    pass
        self.assertEqual(legacy.load()["unknown_browser_state"], {"fixture": True})

    def test_malformed_legacy_state_is_left_untouched(self):
        _, legacy = self.make_bundle()
        raw = b'{"profile":{"info_cache":{"Profile 1":null}}}'
        legacy.path.parent.mkdir(parents=True, exist_ok=True)
        legacy.path.write_bytes(raw)
        with self.assertRaises(ProfileManagerError):
            legacy.load()
        self.assertEqual(legacy.path.read_bytes(), raw)

    def test_mirror_restore_reverts_legacy_when_catalog_publication_fails(self):
        catalog_store, legacy = self.make_bundle()
        original_state = {"profile": {"info_cache": {"Legacy": {"name": "Legacy"}}}, "fixture": True}
        legacy.save(original_state)
        original_bytes = legacy.path.read_bytes()
        coordinator = MirrorCoordinator(catalog_store, legacy, enabled=True)
        catalog = self.make_catalog(self.paths)
        with patch.object(catalog_store, "save", side_effect=ProfileManagerError("synthetic catalog failure")):
            with self.assertRaises(ProfileManagerError):
                coordinator.save(catalog)
        self.assertEqual(legacy.path.read_bytes(), original_bytes)
        self.assertEqual(legacy.load()["profile"]["info_cache"]["Legacy"]["name"], "Legacy")

    def test_chromium_owned_profile_state_is_not_a_catalog_input(self):
        catalog_store, legacy = self.make_bundle()
        profile_state = self.paths.profiles_dir / "profile_0001" / "Local State"
        profile_state.parent.mkdir(parents=True)
        profile_state.write_text('{"profile":{"last_used":"Default"}}', encoding="utf-8")
        self.assertIsNone(catalog_store.load())
        with self.assertRaises(ProfileManagerError):
            legacy.load()
        self.assertEqual(profile_state.read_text(encoding="utf-8"), '{"profile":{"last_used":"Default"}}')


if __name__ == "__main__":
    unittest.main()
