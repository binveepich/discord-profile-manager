"""Regression coverage for the product-candidate patch boundaries."""

import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from revamped import environment
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.processes import ChromiumProcessInspector


class PendingProcess:
    def poll(self):
        return None


class TargetedEnvironmentExportLaunchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dpm-targeted-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.launch_calls = []

        def process_factory(command, **_kwargs):
            self.launch_calls.append(command)
            return PendingProcess()

        self.application = compose_product_candidate(
            self.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
            process_factory=process_factory,
        )
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)

    def test_new_profiles_persist_distinct_environment_without_device_scale(self):
        first = self.api.create_profile("First", environment_payload={"preset": "desktop"})
        second = self.api.create_profile("Second", environment_payload={"preset": "desktop"})
        self.assertNotEqual(
            first["environment"]["environment_signature"],
            second["environment"]["environment_signature"],
        )
        for row in (first, second):
            record = self.application.profile_service.get_profile_record(row["profile_id"])
            self.assertEqual(
                record["environment_config"]["environment_schema"],
                environment.PRODUCT_ENVIRONMENT_SCHEMA,
            )
            self.assertNotIn("device_scale_factor", record["environment_config"])
            command = self.application.launcher.build_command(
                row["profile_id"],
                self.application.profile_service.get_profile_dir(row["profile_id"]),
                record,
            )
            self.assertFalse(any("force-device-scale" in item for item in command))

    def test_mobile_identity_keeps_desktop_usable_physical_bounds(self):
        self.api.create_profile("Mobile")
        row = self.api.generate_environment("profile_0001", "Mobile")
        geometry = row["environment"]["window_geometry"]
        self.assertGreater(geometry["width"], 0)
        self.assertGreater(geometry["height"], 0)
        self.assertNotEqual((geometry["width"], geometry["height"]), (390, 844))
        work_area = geometry["work_area"]
        self.assertLessEqual(geometry["x"] + geometry["width"], work_area["right"])
        self.assertLessEqual(geometry["y"] + geometry["height"], work_area["bottom"])

    def test_stt_position_controls_bounded_window_geometry(self):
        work_area = {"left": 100, "top": 80, "right": 1700, "bottom": 980}
        expected_slots = {1: 0, 2: 1, 99: 0, 100: 1}
        bounds = {}
        for position, expected_slot in expected_slots.items():
            bounds[position] = environment.product_window_bounds(position, work_area=work_area)
            self.assertEqual(bounds[position]["slot"], expected_slot)
            geometry = bounds[position]
            self.assertGreaterEqual(geometry["x"], work_area["left"])
            self.assertGreaterEqual(geometry["y"], work_area["top"])
            self.assertLessEqual(geometry["x"] + geometry["width"], work_area["right"])
            self.assertLessEqual(geometry["y"] + geometry["height"], work_area["bottom"])
        self.assertLess(bounds[1]["x"], bounds[2]["x"])
        self.assertEqual(bounds[1]["width"], bounds[2]["width"])

    def test_first_three_profiles_keep_the_same_side_rule_in_a_group_launch(self):
        rows = [self.api.create_profile(f"Profile {number}") for number in range(1, 4)]
        profile_ids = [row["profile_id"] for row in rows]
        positions = {profile_id: position for position, profile_id in enumerate(profile_ids, 1)}
        slots = [environment.window_slot_for_position(position) for position in positions.values()]

        self.assertEqual(profile_ids, ["profile_0001", "profile_0002", "profile_0003"])
        self.assertEqual(slots, [0, 1, 0])
        for profile_id, position in positions.items():
            record = self.application.profile_service.get_profile_record(profile_id)
            command = self.application.launcher.build_command(
                profile_id,
                self.application.profile_service.get_profile_dir(profile_id),
                record,
            )
            bounds = environment.product_window_bounds(position)
            self.assertEqual(bounds["slot"], environment.window_slot_for_position(position))
            self.assertIn(f"--window-position={bounds['x']},{bounds['y']}", command)
            self.assertIn(f"--window-size={bounds['width']},{bounds['height']}", command)

        launcher = self.application.launcher
        launched = []

        def capture_product_launch(profile_id):
            record = self.application.profile_service.get_profile_record(profile_id)
            command = launcher.build_command(
                profile_id,
                self.application.profile_service.get_profile_dir(profile_id),
                record,
            )
            launched.append((profile_id, command))
            return True

        with patch.object(launcher, "launch_discord", side_effect=capture_product_launch):
            job_id = self.api.launch_batch(profile_ids, delay=0)
            deadline = time.monotonic() + 3
            state = self.api.get_job(job_id)
            while state["status"] not in {"completed", "failed", "cancelled"} and time.monotonic() < deadline:
                time.sleep(0.01)
                state = self.api.get_job(job_id)

        self.assertEqual(state["status"], "completed")
        self.assertEqual([profile_id for profile_id, _command in launched], profile_ids)
        for profile_id, command in launched:
            bounds = environment.product_window_bounds(positions[profile_id])
            self.assertIn(f"--window-position={bounds['x']},{bounds['y']}", command)

    def test_restored_window_correction_receives_first_three_profile_bounds(self):
        work_area = {"left": 100, "top": 80, "right": 1700, "bottom": 980}
        for number in range(1, 4):
            self.api.create_profile(f"Profile {number}")
        launcher = self.application.launcher
        launcher.window_placement_builder = lambda position: [position]
        launcher.window_bounds_builder = lambda position: environment.product_window_bounds(
            position, work_area=work_area
        )
        corrections = []

        class ImmediateThread:
            def __init__(self, target, kwargs, **_options):
                self.target = target
                self.kwargs = kwargs

            def start(self):
                self.target(**self.kwargs)

        with patch("revamped.launcher.sys.platform", "win32"), \
             patch("revamped.launcher.threading.Thread", ImmediateThread), \
             patch("revamped.launcher.correct_profile_window_placement",
                   side_effect=lambda **kwargs: corrections.append(kwargs)):
            for profile_id in ("profile_0001", "profile_0002", "profile_0003"):
                launcher._schedule_window_correction(
                    profile_id,
                    self.root / "profiles" / profile_id,
                    type("Process", (), {"pid": 4242})(),
                )

        self.assertEqual([item["bounds"]["slot"] for item in corrections], [0, 1, 0])
        self.assertEqual(
            [item["bounds"] for item in corrections],
            [environment.product_window_bounds(position, work_area=work_area) for position in (1, 2, 3)],
        )

    def test_missing_or_malformed_positions_fall_back_left_without_raising(self):
        for position in (None, 0, "legacy-profile"):
            with self.subTest(position=position):
                self.assertEqual(environment.window_slot_for_position(position), 0)
                geometry = environment.product_window_bounds(
                    position, work_area=(0, 0, 1280, 800)
                )
                self.assertEqual(geometry["slot"], 0)
                self.assertGreaterEqual(geometry["x"], 0)
                self.assertLessEqual(geometry["x"] + geometry["width"], 1280)

    def test_windows_placement_skips_hard_coded_bounds_if_display_geometry_is_unavailable(self):
        with patch("revamped.environment.get_windows_work_area", return_value=None):
            with patch("revamped.environment.sys.platform", "win32"):
                self.assertEqual(
                    environment.product_window_placement_arguments(1),
                    [],
                )

    def test_launch_command_places_each_profile_by_catalog_position(self):
        rows = [self.api.create_profile(f"Profile {number}") for number in range(1, 5)]
        positions = {row["profile_id"]: position for position, row in enumerate(rows, 1)}
        for row in reversed(rows):
            profile_id = row["profile_id"]
            record = self.application.profile_service.get_profile_record(profile_id)
            command = self.application.launcher.build_command(
                profile_id,
                self.application.profile_service.get_profile_dir(profile_id),
                record,
            )
            geometry = environment.product_window_bounds(positions[profile_id])
            self.assertIn(
                f"--window-position={geometry['x']},{geometry['y']}", command
            )
            self.assertIn(
                f"--window-size={geometry['width']},{geometry['height']}", command
            )
            self.assertFalse(environment.product_environment_launch_arguments(record))

    def test_deleted_neighbor_moves_later_profiles_to_their_new_stt_side(self):
        desktop = {"preset": "desktop"}
        first = self.api.create_profile("First", environment_payload=desktop)["profile_id"]
        middle = self.api.create_profile("Middle", environment_payload=desktop)["profile_id"]
        last = self.api.create_profile("Last", environment_payload=desktop)["profile_id"]
        profiles = self.application.profile_service
        self.assertEqual(profiles.display_position(last), 3)
        self.api.delete_profiles([middle], confirmed=True)
        row = next(row for row in self.api.list_profiles() if row["profile_id"] == last)
        self.assertEqual(row["stt"], "0002")
        self.assertEqual(row["environment"]["window_geometry"]["slot"], 1)
        self.assertEqual(profiles.display_position(first), 1)
        self.assertEqual(profiles.display_position(last), 2)
        command = self.application.launcher.build_command(
            last,
            profiles.get_profile_dir(last),
            profiles.get_profile_record(last),
        )
        expected = environment.product_window_bounds(2)
        self.assertEqual(expected["slot"], 1)
        self.assertIn(f"--window-position={expected['x']},{expected['y']}", command)

    def test_full_exports_use_endpoint_only_proxy_schema(self):
        row = self.api.create_profile(
            "Proxy endpoint", proxy_payload="https://proxy.example:8443",
        )
        selected = [row["profile_id"]]
        json_export = self.api.export_json(selected)
        json_data = json.loads(json_export["content"])
        csv_data = self.api.export_csv(selected)["content"]
        txt_data = self.api.export_txt(selected)["content"]
        exported = json_data[0]
        self.assertEqual(list(exported), list(json_export["columns"]))
        self.assertEqual(exported["proxy_scheme"], "https")
        self.assertEqual(exported["proxy_host"], "proxy.example")
        self.assertEqual(exported["proxy_port"], 8443)
        for key in ("proxy_username", "proxy_password"):
            self.assertNotIn(key, exported)
            self.assertNotIn(key, csv_data)
            self.assertNotIn(key, txt_data)

    def test_non_launch_operations_never_call_process_factory(self):
        self.api.create_profile("Create")
        self.api.update_profile("profile_0001", "Updated", environment_payload={"preset": "Desktop"})
        self.api.generate_environment("profile_0001", "Desktop")
        self.api.import_accounts_txt_sync("imported@example.com:import-password")
        self.api.get_runtime_info()
        self.assertEqual(self.launch_calls, [])

    def test_only_explicit_launch_api_calls_process_factory(self):
        browser = self.root / "browser" / "chrome.exe"
        browser.parent.mkdir(parents=True, exist_ok=True)
        browser.write_bytes(b"synthetic runtime")
        row = self.api.create_profile("Launch")
        self.api.launch_profile(row["profile_id"])
        self.assertEqual(len(self.launch_calls), 1)


if __name__ == "__main__":
    unittest.main()
