"""R11 profile runtime settings contracts using disposable workspaces only."""

import json
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped import environment
from revamped.core import ProxyValidationError
from revamped.main import compose
from revamped.processes import ChromiumProcessInspector


class R11RuntimeSettingsTests(unittest.TestCase):
    """The coherent Runtime Settings UI is backed by stable service contracts."""

    def setUp(self):
        self.workspace = DisposableWorkspace("r11-runtime-settings-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.application = self.restart()
        self.profile_id = self.application.profile_service.create_profile(
            "R11 disposable runtime profile"
        )

    def restart(self):
        return compose(
            self.workspace.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )

    def command_for(self, application=None, profile_id=None):
        application = application or self.application
        profile_id = profile_id or self.profile_id
        profile_service = application.profile_service
        return application.launcher.build_command(
            profile_id,
            profile_service.require_profile_dir(profile_id),
            profile_service.get_profile_record(profile_id),
        )

    def test_preset_switching_exposes_supported_chromium_identity_families(self):
        cases = (
            ("Default Desktop", "desktop", None),
            ("Windows Chromium", "windows_chromium", "Windows NT"),
            ("Linux Chromium", "linux_chromium", "X11; Linux"),
            ("Android Chromium", "android_chromium", "Android"),
            ("Custom", "custom", None),
            ("Generated / Random", "generated", None),
        )

        for label, canonical, user_agent_marker in cases:
            with self.subTest(preset=label):
                custom_config = None
                if canonical == "custom":
                    custom_config = {
                        "user_agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chromium/123.0.0.0 Safari/537.36"
                        ),
                    }
                self.application.profile_service.save_runtime_settings(
                    self.profile_id,
                    label,
                    environment_config=custom_config,
                )
                settings = self.application.profile_service.get_runtime_settings(
                    self.profile_id
                )
                identity = settings["environment"]

                self.assertEqual(identity["preset"], canonical)
                self.assertIn("window_size_policy", identity)
                self.assertIn("timezone", identity)
                if user_agent_marker:
                    self.assertIn(user_agent_marker, identity["user_agent"])
                    self.assertIn("Chrom", identity["user_agent"])
                    self.assertNotIn("iPhone", identity["user_agent"])
                    self.assertNotIn("Version/", identity["user_agent"])

    def test_generated_environment_helper_is_deterministic_and_family_consistent(self):
        first = environment.deterministic_generated_environment(self.profile_id, generation=0)
        second = environment.deterministic_generated_environment(self.profile_id, generation=0)
        next_generation = environment.deterministic_generated_environment(
            self.profile_id, generation=1
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, next_generation)
        for generated in (first, next_generation):
            self.assertIn("user_agent", generated)
            self.assertIn("language", generated)
            self.assertIn("device_scale_factor", generated)
            self.assertIn("touch_mode", generated)
            self.assertTrue(generated["user_agent"])
            self.assertIn("Chrom", generated["user_agent"])
            self.assertNotIn("iPhone", generated["user_agent"])
            self.assertNotIn("Version/", generated["user_agent"])
            self.assertIsInstance(generated["touch_mode"], bool)
            if "Android" in generated["user_agent"]:
                self.assertTrue(generated["touch_mode"])
                self.assertGreaterEqual(generated["device_scale_factor"], 1.0)

    def test_generated_identity_is_persisted_until_explicitly_regenerated(self):
        self.application.profile_service.save_runtime_settings(
            self.profile_id, "generated"
        )
        saved = self.application.profile_service.get_runtime_settings(self.profile_id)
        restarted = self.restart()
        after_restart = restarted.profile_service.get_runtime_settings(self.profile_id)

        self.assertEqual(after_restart, saved)
        regenerated = restarted.profile_service.regenerate_environment(self.profile_id)
        after_regeneration = restarted.profile_service.get_runtime_settings(self.profile_id)
        self.assertEqual(after_regeneration, regenerated)
        self.assertEqual(after_regeneration["environment"]["preset"], "generated")
        self.assertNotEqual(
            after_regeneration["environment"], saved["environment"],
            "Generated identities must change only through the explicit action.",
        )

        final_restart = self.restart()
        self.assertEqual(
            final_restart.profile_service.get_runtime_settings(self.profile_id),
            after_regeneration,
        )

    def test_explicit_custom_user_agent_reaches_chromium_command(self):
        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chromium/123.0.0.0 Safari/537.36"
        )
        self.application.profile_service.save_runtime_settings(
            self.profile_id,
            "custom",
            environment_config={
                "user_agent": user_agent,
                "language": "vi-VN",
                "device_scale_factor": 1.25,
                "touch_mode": False,
                "timezone": "Asia/Ho_Chi_Minh",
                "window_size_policy": "custom",
                "window_width": 1280,
                "window_height": 820,
            },
        )

        restarted = self.restart()
        identity = restarted.profile_service.get_runtime_settings(self.profile_id)[
            "environment"
        ]
        command = self.command_for(restarted)
        self.assertEqual(identity["user_agent"], user_agent)
        self.assertEqual(identity["language"], "vi-VN")
        self.assertEqual(identity["device_scale_factor"], 1.25)
        self.assertFalse(identity["touch_mode"])
        self.assertEqual(identity["timezone"], "Asia/Ho_Chi_Minh")
        self.assertIn(f"--user-agent={user_agent}", command)
        self.assertIn("--lang=vi-VN", command)
        self.assertIn("--force-device-scale-factor=1.25", command)
        self.assertIn("--touch-events=disabled", command)
        self.assertIn("--window-size=1280,820", command)
        self.assertFalse(any("timezone" in argument for argument in command))
        self.assertNotIn("--use-mobile-user-agent", command)

    def test_android_identity_does_not_impose_a_phone_sized_window(self):
        self.application.profile_service.save_runtime_settings(
            self.profile_id, "android_chromium"
        )
        identity = self.application.profile_service.get_runtime_settings(
            self.profile_id
        )["environment"]
        default_command = self.command_for()

        self.assertIn("Android", identity["user_agent"])
        self.assertTrue(identity["touch_mode"])
        self.assertNotIn("--window-size=390,844", default_command)
        self.assertNotIn("--use-mobile-user-agent", default_command)
        self.assertIn(f"--user-agent={identity['user_agent']}", default_command)

        self.application.profile_service.save_runtime_settings(
            self.profile_id,
            "windows_chromium",
            environment_config={
                "window_size_policy": "custom",
                "window_width": 1366,
                "window_height": 900,
            },
        )
        self.application.profile_service.save_runtime_settings(
            self.profile_id,
            "android_chromium",
        )
        switched_identity_command = self.command_for()
        self.assertIn("--window-size=1366,900", switched_identity_command)
        switched_identity = self.application.profile_service.get_runtime_settings(
            self.profile_id
        )["environment"]
        self.assertIn("Android", switched_identity["user_agent"])

        self.application.profile_service.save_runtime_settings(
            self.profile_id,
            "android_chromium",
            environment_config={
                "window_size_policy": "custom",
                "window_width": 1440,
                "window_height": 900,
            },
        )
        custom_window_command = self.command_for()
        self.assertIn("--window-size=1440,900", custom_window_command)
        self.assertNotIn("--window-size=390,844", custom_window_command)
        self.assertTrue(any(arg.startswith("--user-agent=") for arg in custom_window_command))

    def test_network_settings_persist_and_reach_chromium_after_restart(self):
        for scheme in ("http", "https", "socks4", "socks5"):
            with self.subTest(scheme=scheme):
                proxy_config = {
                    "enabled": True,
                    "scheme": scheme,
                    "host": "127.0.0.1",
                    "port": 1080,
                }
                self.application.profile_service.save_runtime_settings(
                    self.profile_id,
                    "linux_chromium",
                    proxy_config=proxy_config,
                )
                restarted = self.restart()
                settings = restarted.profile_service.get_runtime_settings(self.profile_id)

                self.assertEqual(settings["network"], proxy_config)
                self.assertIn(
                    f"--proxy-server={scheme}://127.0.0.1:1080",
                    self.command_for(restarted),
                )

        self.application.profile_service.save_runtime_settings(
            self.profile_id, "linux_chromium", proxy_config={"enabled": False}
        )
        self.assertEqual(
            self.application.profile_service.get_runtime_settings(self.profile_id)["network"],
            {"enabled": False, "scheme": None, "host": None, "port": None},
        )
        self.assertFalse(any(
            argument.startswith("--proxy-") for argument in self.command_for()
        ))

    def test_unified_runtime_settings_reject_proxy_auth_without_changing_profile(self):
        before = self.application.profile_service.get_profile_record(self.profile_id)

        for credentials in (
            {"username": "synthetic-user"},
            {"username": "synthetic-user", "password": "synthetic-password"},
        ):
            with self.subTest(credential_fields=sorted(credentials)):
                with self.assertRaises(ProxyValidationError):
                    self.application.profile_service.save_runtime_settings(
                        self.profile_id,
                        "windows_chromium",
                        proxy_config={
                            "enabled": True,
                            "scheme": "http",
                            "host": "proxy.example",
                            "port": 8080,
                            **credentials,
                        },
                    )

        self.assertEqual(
            self.application.profile_service.get_profile_record(self.profile_id), before
        )

    def test_existing_r10_metadata_loads_as_runtime_settings_without_data_loss(self):
        # This mirrors the persisted R10 shape rather than writing through the
        # new API, so migration/defaulting is tested at the storage boundary.
        catalog = json.loads(
            self.application.paths.profiles_json.read_text(encoding="utf-8")
        )
        record = catalog["profiles"][0]
        record.update({
            "environment_preset": "mobile",
            "environment_config": {
                "viewport_width": 390,
                "viewport_height": 844,
                "device_scale_factor": 1.0,
                "language": "en-US",
                "timezone": "UTC",
                "mobile_mode": True,
                "touch_mode": True,
            },
            "proxy_enabled": True,
            "proxy_scheme": "https",
            "proxy_host": "legacy-proxy.example",
            "proxy_port": 443,
        })
        self.application.paths.profiles_json.write_text(
            json.dumps(catalog), encoding="utf-8"
        )

        restarted = self.restart()
        settings = restarted.profile_service.get_runtime_settings(self.profile_id)
        command = self.command_for(restarted)

        self.assertIn("environment", settings)
        self.assertIn("network", settings)
        self.assertTrue(settings["environment"]["user_agent"])
        self.assertEqual(settings["environment"]["timezone"], "UTC")
        self.assertEqual(settings["network"], {
            "enabled": True,
            "scheme": "https",
            "host": "legacy-proxy.example",
            "port": 443,
        })
        self.assertIn("--proxy-server=https://legacy-proxy.example:443", command)
        self.assertTrue(restarted.profile_service.require_profile_dir(self.profile_id).is_dir())


if __name__ == "__main__":
    unittest.main()
