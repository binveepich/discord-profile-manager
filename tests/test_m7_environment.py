"""M7 browser environment preset tests using disposable synthetic profiles."""

import json
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

import test_m1_runtime as m1
from test_m6_gui import FakeTree, FakeVar


class EnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_runtime = m1.RuntimeTests.make_runtime
    make_profiles = m1.RuntimeTests.make_profiles

    def test_existing_profile_defaults_to_desktop(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Desktop default")

        self.assertEqual(profiles.get_environment(profile_id)["preset"], "desktop")
        self.assertEqual(
            self.manager.environment_launch_arguments(
                profiles.get_profile_metadata()[0]
            ),
            [],
        )

    def test_profile_actions_do_not_expose_ambiguous_generic_edit(self):
        setup_source = inspect.getsource(self.manager.ProfileManagerApp.setup_ui)
        self.assertNotIn('( "Edit", self.edit_profile', setup_source)
        self.assertNotIn('("Edit", self.edit_profile', setup_source)
        self.assertIn('text="Account Actions"', setup_source)
        self.assertIn('command=self.view_account', setup_source)

    def test_environment_editor_states_are_distinct_and_use_preset_defaults(self):
        desktop = self.manager.environment_editor_state(
            "desktop", self.manager.MOBILE_ENVIRONMENT_DEFAULTS
        )
        mobile = self.manager.environment_editor_state("mobile")
        custom = self.manager.environment_editor_state("custom", {
            "width": 1000, "height": 700, "scale_factor": 1.25,
            "language": "en-US", "mobile": False, "touch": True,
        })

        self.assertFalse(desktop["editable"])
        self.assertEqual(desktop["viewport_width"], "Chromium default")
        self.assertEqual(desktop["device_scale_factor"], "Chromium default")
        self.assertFalse(desktop["mobile_mode"])
        self.assertFalse(desktop["touch_mode"])
        self.assertEqual(mobile["viewport_width"], self.manager.MOBILE_ENVIRONMENT_DEFAULTS["viewport_width"])
        self.assertEqual(mobile["viewport_height"], self.manager.MOBILE_ENVIRONMENT_DEFAULTS["viewport_height"])
        self.assertEqual(mobile["device_scale_factor"], self.manager.MOBILE_ENVIRONMENT_DEFAULTS["device_scale_factor"])
        self.assertTrue(mobile["mobile_mode"])
        self.assertTrue(mobile["touch_mode"])
        self.assertTrue(custom["editable"])
        self.assertEqual(custom["viewport_width"], 1000)
        self.assertFalse(custom["mobile_mode"])
        self.assertTrue(custom["touch_mode"])

    def test_environment_editor_switching_clears_mobile_state_for_desktop(self):
        desktop = self.manager.environment_editor_state("desktop")
        mobile = self.manager.environment_editor_state("mobile")
        back_to_desktop = self.manager.environment_editor_state("desktop", mobile)

        self.assertTrue(mobile["mobile_mode"])
        self.assertTrue(mobile["touch_mode"])
        self.assertEqual(back_to_desktop["viewport_width"], "Chromium default")
        self.assertEqual(back_to_desktop["viewport_height"], "Chromium default")
        self.assertFalse(back_to_desktop["mobile_mode"])
        self.assertFalse(back_to_desktop["touch_mode"])
        self.assertEqual(self.manager.environment_launch_arguments({
            "environment_preset": desktop["preset"]
        }), [])

    def test_saving_desktop_discards_stale_mobile_overrides(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Desktop after mobile")
        profiles.set_environment(profile_id, "mobile")
        profiles.set_environment(profile_id, "desktop", self.manager.MOBILE_ENVIRONMENT_DEFAULTS)

        record = profiles.get_profile_metadata()[0]
        self.assertEqual(record["environment_preset"], "desktop")
        self.assertNotIn("environment_config", record)
        self.assertEqual(self.manager.environment_launch_arguments(record), [])

    def test_sidebar_is_scrollable_and_keeps_all_action_groups_in_one_panel(self):
        setup_source = inspect.getsource(self.manager.ProfileManagerApp.setup_ui)
        self.assertIn("sidebar_canvas = tk.Canvas", setup_source)
        self.assertIn("sidebar_scrollbar = tk.Scrollbar", setup_source)
        self.assertIn("text=\"Quick Launch\"", setup_source)
        self.assertIn("text=\"Environment\"", setup_source)
        self.assertIn("text=\"Profile Actions\"", setup_source)
        self.assertIn("text=\"Account Actions\"", setup_source)
        self.assertTrue(hasattr(self.manager.ProfileManagerApp, "_on_sidebar_mousewheel"))

    def test_old_default_metadata_remains_desktop_compatible(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Legacy default")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        catalog["profiles"][0]["environment_preset"] = "default"
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        restarted = self.manager.ProfileManager()
        self.assertEqual(restarted.get_environment(profile_id)["preset"], "desktop")
        self.assertEqual(
            self.manager.environment_launch_arguments(
                restarted.get_profile_metadata()[0]
            ),
            [],
        )

    def test_missing_environment_metadata_remains_desktop_compatible(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Missing environment")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        catalog["profiles"][0].pop("environment_preset")
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        restarted = self.manager.ProfileManager()
        self.assertEqual(restarted.get_environment(profile_id)["preset"], "desktop")
        self.assertEqual(
            self.manager.environment_launch_arguments(
                restarted.get_profile_metadata()[0]
            ),
            [],
        )

    def test_desktop_preset_persists(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Desktop")
        profiles.set_environment(profile_id, "Desktop")

        record = profiles.get_profile_metadata()[0]
        self.assertEqual(record["environment_preset"], "desktop")
        self.assertEqual(self.manager.ProfileManager().get_environment(profile_id)["preset"], "desktop")

    def test_mobile_preset_persists_after_restart(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Mobile")
        profiles.set_environment(profile_id, "Mobile")

        restarted = self.manager.ProfileManager()
        record = restarted.get_profile_metadata()[0]
        environment = restarted.get_environment(profile_id)
        self.assertEqual(record["environment_preset"], "mobile")
        self.assertEqual(environment["viewport_width"], 390)
        self.assertTrue(environment["mobile_mode"])
        self.assertTrue(environment["touch_mode"])

    def test_custom_preset_persists_after_restart(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Custom")
        profiles.set_environment(profile_id, "Custom", {
            "width": "1024",
            "height": "768",
            "scale_factor": "1.25",
            "locale": "vi_VN",
            "timezone": "Asia/Ho_Chi_Minh",
            "mobile": False,
            "touch": True,
        })

        restarted = self.manager.ProfileManager()
        environment = restarted.get_environment(profile_id)
        self.assertEqual(environment["preset"], "custom")
        self.assertEqual(environment["viewport_width"], 1024)
        self.assertEqual(environment["viewport_height"], 768)
        self.assertEqual(environment["device_scale_factor"], 1.25)
        self.assertEqual(environment["language"], "vi-VN")
        self.assertEqual(environment["timezone"], "Asia/Ho_Chi_Minh")
        self.assertFalse(environment["mobile_mode"])
        self.assertTrue(environment["touch_mode"])

    def test_multiple_profiles_keep_different_presets(self):
        profiles = self.make_profiles()
        desktop = profiles.create_profile("Desktop")
        mobile = profiles.create_profile("Mobile")
        custom = profiles.create_profile("Custom")
        profiles.set_environment(mobile, "mobile")
        profiles.set_environment(custom, "custom", {
            "width": 1280, "height": 720, "scale_factor": 1,
            "language": "en-US", "mobile_mode": False, "touch_mode": False,
        })

        records = {record["profile_id"]: record for record in profiles.get_profile_metadata()}
        self.assertEqual(self.manager.environment_launch_arguments(records[desktop]), [])
        self.assertIn("--use-mobile-user-agent", self.manager.environment_launch_arguments(records[mobile]))
        self.assertIn("--window-size=1280,720", self.manager.environment_launch_arguments(records[custom]))
        self.assertNotIn("--use-mobile-user-agent", self.manager.environment_launch_arguments(records[custom]))

    def test_invalid_preset_falls_back_to_desktop(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Invalid preset")
        profiles.set_environment(profile_id, "not-a-preset")

        record = profiles.get_profile_metadata()[0]
        self.assertEqual(record["environment_preset"], "desktop")
        self.assertEqual(self.manager.environment_launch_arguments(record), [])

    def test_invalid_custom_values_are_safely_ignored(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Invalid values")
        profiles.set_environment(profile_id, "custom", {
            "width": -1,
            "height": "not-a-number",
            "scale_factor": "nan",
            "timezone": "Not/A_Timezone",
            "locale": "not a locale",
        })

        record = profiles.get_profile_metadata()[0]
        self.assertEqual(record["environment_preset"], "custom")
        self.assertEqual(record["environment_config"], {})
        self.assertEqual(profiles.get_environment(profile_id)["preset"], "desktop")
        self.assertEqual(self.manager.environment_launch_arguments(record), [])

    def test_malformed_custom_configuration_falls_back_to_desktop(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Malformed config")
        catalog = json.loads(self.manager.PROFILES_JSON.read_text(encoding="utf-8"))
        catalog["profiles"][0]["environment_preset"] = "custom"
        catalog["profiles"][0]["environment_config"] = ["broken"]
        self.manager.PROFILES_JSON.write_text(json.dumps(catalog), encoding="utf-8")

        restarted = self.manager.ProfileManager()
        record = restarted.get_profile_metadata()[0]
        self.assertEqual(restarted.get_environment(profile_id)["preset"], "desktop")
        self.assertEqual(self.manager.environment_launch_arguments(record), [])

    def test_desktop_launch_configuration_is_unchanged(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Desktop launch")
        profiles.set_environment(profile_id, "desktop")

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        self.assertEqual(self.popen.call_args.args[0], [
            str(self.runtime),
            f"--user-data-dir={self.profiles / profile_id}",
            "--new-window", "--no-first-run", "--no-default-browser-check",
            "--disable-sync", "--process-per-site", "https://discord.com/app",
        ])
        self.assertEqual(self.popen.call_args.kwargs["shell"], False)

    def test_mobile_launch_configuration_is_generated(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Mobile launch")
        profiles.set_environment(profile_id, "mobile")

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        command = self.popen.call_args.args[0]
        self.assertIn("--window-size=390,844", command)
        self.assertIn("--force-device-scale-factor=2", command)
        self.assertIn("--lang=en-US", command)
        self.assertIn("--use-mobile-user-agent", command)
        self.assertIn("--touch-events=enabled", command)

    def test_custom_launch_configuration_is_generated(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Custom launch")
        profiles.set_environment(profile_id, "custom", {
            "width": 1200, "height": 800, "scale_factor": 1.5,
            "language": "en-US", "mobile_mode": True, "touch_mode": False,
            "timezone": "UTC",
        })

        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id))
        command = self.popen.call_args.args[0]
        self.assertIn("--window-size=1200,800", command)
        self.assertIn("--force-device-scale-factor=1.5", command)
        self.assertIn("--lang=en-US", command)
        self.assertIn("--use-mobile-user-agent", command)
        self.assertIn("--touch-events=disabled", command)
        self.assertNotIn("--timezone=UTC", command)

    def test_timezone_is_validated_and_persisted_but_not_faked_at_launch(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Timezone")
        profiles.set_environment(profile_id, "custom", {
            "width": 800, "height": 600, "timezone": "UTC"
        })
        environment = profiles.get_environment(profile_id)

        self.assertEqual(environment["timezone"], "UTC")
        self.assertIsNone(self.manager.normalize_timezone("Not/A_Timezone"))

    def test_environment_arguments_do_not_leak_between_profiles(self):
        profiles = self.make_profiles()
        first = profiles.create_profile("First")
        second = profiles.create_profile("Second")
        profiles.set_environment(first, "mobile")
        profiles.set_environment(second, "desktop")
        records = {record["profile_id"]: record for record in profiles.get_profile_metadata()}

        first_args = self.manager.environment_launch_arguments(records[first])
        second_args = self.manager.environment_launch_arguments(records[second])
        self.assertTrue(first_args)
        self.assertEqual(second_args, [])

    def test_no_fingerprint_spoofing_arguments_or_metadata_are_introduced(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Scope")
        profiles.set_environment(profile_id, "custom", {
            "width": 800, "height": 600, "language": "en-US"
        })
        record = profiles.get_profile_metadata()[0]
        serialized = json.dumps(record).casefold()
        arguments = " ".join(self.manager.environment_launch_arguments(record)).casefold()
        for forbidden in ("canvas", "webgl", "audiocontext", "fingerprint", "evasion", "spoof"):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, arguments)

    def test_m6_search_and_status_components_remain_present(self):
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app._closing = False
        app.search_var = FakeVar("beta")
        app._profile_rows = [
            {"profile_id": "one", "display_name": "Alpha", "account": "-",
             "environment": "Desktop", "proxy": "Off", "status": "Closed",
             "last_opened": "Never", "created_at": "", "last_opened_sort": ""},
            {"profile_id": "two", "display_name": "Beta", "account": "-",
             "environment": "Mobile", "proxy": "Off", "status": "Closed",
             "last_opened": "Never", "created_at": "", "last_opened_sort": ""},
        ]
        self.assertEqual(
            [row["profile_id"] for row in app._filtered_profile_rows()],
            ["two"],
        )

        profile_path = self.work / "profiles" / "profile_0001"
        profile_path.mkdir(parents=True)
        status_row = {
            "profile_id": "profile_0001", "profile_path": str(profile_path),
            "status": "Closed",
        }
        app._profile_rows = [status_row]
        app.table_rows = [status_row]
        app.tree = FakeTree()
        app.tree.insert("", "end", iid="profile_0001", values=(
            "Profile", "-", "Desktop", "Off", "Closed", "Never", "profile_0001"
        ))
        with patch.object(self.manager, "browser_using_directory", return_value=True):
            app._refresh_cached_statuses()
        self.assertEqual(status_row["status"], "Open")
        self.assertEqual(app.tree.item("profile_0001", "values")[4], "Open")


if __name__ == "__main__":
    unittest.main()
