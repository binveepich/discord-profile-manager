"""R2 deterministic model and timestamp contract tests."""

from datetime import datetime, timezone
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ProjectPaths
from revamped.models import (
    ProfileRecord,
    new_profile_record,
    profile_pairs,
    timestamp_from_epoch,
    utc_timestamp,
)


class ModelContractTests(unittest.TestCase):
    def test_fixed_clock_timestamps_are_deterministic(self):
        fixed = lambda: datetime(2026, 1, 2, 3, 4, 5, 987654, tzinfo=timezone.utc)
        self.assertEqual(utc_timestamp(fixed), "2026-01-02T03:04:05Z")
        self.assertEqual(timestamp_from_epoch(0, fixed), "1970-01-01T00:00:00Z")
        self.assertEqual(timestamp_from_epoch("bad", fixed), "2026-01-02T03:04:05Z")

    def test_record_round_trip_preserves_unknown_non_sensitive_fields(self):
        source = {
            "profile_id": "profile_0001",
            "display_name": "One",
            "profile_directory": "profiles/profile_0001",
            "created_at": "2026-01-01T00:00:00Z",
            "last_opened_at": None,
            "environment_preset": "default",
            "proxy_enabled": False,
            "ui_color": "blue",
        }
        record = ProfileRecord.from_mapping(source)
        result = record.to_mapping()
        self.assertEqual(result["ui_color"], "blue")
        self.assertEqual(result["profile_id"], "profile_0001")
        self.assertNotIn("password", result)

    def test_new_record_uses_safe_relative_path_and_fixed_time(self):
        with DisposableWorkspace() as workspace:
            paths = ProjectPaths(workspace.root)
            fixed = lambda: datetime(2026, 2, 3, tzinfo=timezone.utc)
            record = new_profile_record(
                "profile_0001", "New", paths.profiles_dir / "profile_0001", paths, clock=fixed
            )
            self.assertEqual(record.profile_directory, "profiles/profile_0001")
            self.assertEqual(record.created_at, "2026-02-03T00:00:00Z")

    def test_profile_pair_sorting_keeps_default_first(self):
        records = [
            {"profile_id": "profile_0002", "display_name": "beta"},
            {"profile_id": "Default", "display_name": "zeta"},
            {"profile_id": "profile_0001", "display_name": "Alpha"},
        ]
        self.assertEqual(profile_pairs(records), [
            ("Default", "zeta"), ("profile_0001", "Alpha"), ("profile_0002", "beta")
        ])


if __name__ == "__main__":
    unittest.main()

