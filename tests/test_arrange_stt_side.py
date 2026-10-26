"""Arrange (tab tiling): odd STT opens on the left half, even STT on the right half."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from revamped import environment
from revamped.main import compose_product_candidate
from revamped.processes import ChromiumProcessInspector


# STT is the compacted display order; profile IDs stay stable. This catalog reproduces the gap
# pattern left by deletions: STT 1 is profile_0012, and from STT 20 onward every ID is one ahead.
CREATED_PROFILE_COUNT = 87
DELETED_PROFILE_NUMBERS = [*range(1, 12), *range(13, 26), 44, 45, 46]
EXPECTED_FIRST_IDS = ["profile_0012", *(f"profile_{n:04d}" for n in range(26, 44)), "profile_0047"]
WORK_AREAS = (
    # One monitor with the taskbar reserved.
    {"left": 0, "top": 0, "right": 1920, "bottom": 1040},
    # Two monitors: Windows reports only the primary work area, so a larger primary must give the same sides.
    {"left": 0, "top": 0, "right": 2560, "bottom": 1400},
)


def expected_side(stt):
    return "left" if stt % 2 == 1 else "right"


class ArrangeSttSideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The catalog is built once: every test here only reads it.
        cls.root = Path(tempfile.mkdtemp(prefix="dpm-arrange-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        cls.application = compose_product_candidate(
            cls.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        cls.profiles = cls.application.profile_service
        cls.profiles.initialize_metadata()
        with cls.profiles.batch_operation():
            for number in range(1, CREATED_PROFILE_COUNT + 1):
                cls.profiles.create_profile(f"Profile {number}")
        cls.profiles.delete_profiles([f"profile_{number:04d}" for number in DELETED_PROFILE_NUMBERS])
        first_ids = [record["profile_id"] for record in cls.profiles.get_profile_metadata()]
        if first_ids[:len(EXPECTED_FIRST_IDS)] != EXPECTED_FIRST_IDS:
            raise AssertionError(f"catalog does not reproduce the live gap pattern: {first_ids[:20]}")

    def _catalog_ids(self):
        return [record["profile_id"] for record in self.profiles.get_profile_metadata()]

    @staticmethod
    def _window_x(command):
        value = next(item for item in command if item.startswith("--window-position="))
        return int(value.split("=", 1)[1].split(",")[0])

    def _sides_by_stt(self, work_area):
        """Return {STT: "left"|"right"} using the real launch command for STT 1..60."""
        launcher = self.application.launcher
        commands = {}
        with patch.object(environment, "get_windows_work_area", return_value=work_area):
            for stt, profile_id in enumerate(self._catalog_ids()[:60], 1):
                record = self.profiles.get_profile_record(profile_id)
                commands[stt] = launcher.build_command(
                    profile_id, self.profiles.get_profile_dir(profile_id), record
                )
        x_values = sorted({self._window_x(command) for command in commands.values()})
        self.assertEqual(len(x_values), 2, "arrange must use exactly one left and one right origin")
        left_x = x_values[0]
        return {
            stt: "left" if self._window_x(command) == left_x else "right"
            for stt, command in commands.items()
        }

    def test_odd_stt_opens_left_and_even_stt_opens_right_for_stt_1_to_60(self):
        for work_area in WORK_AREAS:
            with self.subTest(work_area=work_area):
                sides = self._sides_by_stt(work_area)
                self.assertEqual(sorted(sides), list(range(1, 61)))
                for stt in range(1, 61):
                    with self.subTest(stt=stt):
                        self.assertEqual(sides[stt], expected_side(stt))

    def test_one_function_maps_stt_to_side(self):
        self.assertEqual(
            [environment.window_slot_for_position(stt) for stt in range(1, 61)],
            [0 if stt % 2 else 1 for stt in range(1, 61)],
        )
        self.assertEqual(environment.window_slot_for_position(1), 0)
        self.assertEqual(environment.window_slot_for_position(2), 1)

    def test_missing_or_invalid_position_falls_back_left(self):
        for position in (None, 0, -3, "2", True):
            with self.subTest(position=position):
                self.assertEqual(environment.window_slot_for_position(position), 0)


if __name__ == "__main__":
    unittest.main()
