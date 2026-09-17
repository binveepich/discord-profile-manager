"""Saved GUI settings must reach the composed launcher after a restart."""

from pathlib import Path
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.extensions import REQUIRED_EXTENSION_NAMES
from revamped.main import compose
from revamped.processes import ChromiumProcessInspector


class PendingProcess:
    def poll(self):
        return None


class R10RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r10-runtime-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.commands = []
        self.inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        self.runtime_fixture = self.workspace.root / "synthetic-runtime" / "chrome.exe"
        self.runtime_fixture.parent.mkdir()
        self.runtime_fixture.write_bytes(b"R10 recorder fixture; never executed")
        self.application = self.restart()
        self.profile_id = self.application.controller.create_profile("R10 disposable")

    def restart(self):
        def recorder(command, **kwargs):
            self.commands.append(command)
            return PendingProcess()

        application = compose(self.workspace.root, process_inspector=self.inspector, process_factory=recorder)
        # Unit checks must work on fresh clones without the ignored runtime.
        # The separate opt-in smoke exercises the real repository executable.
        application.launcher.launcher_path = self.runtime_fixture
        return application

    def open_after_restart(self):
        application = self.restart()
        application.controller.refresh()
        application.controller.set_selection([self.profile_id])
        self.assertEqual(application.controller.open_selected(), {
            "requested": 1, "running": 0, "errors": [],
        })
        return application, self.commands[-1]

    def test_saved_custom_environment_and_proxy_reach_command_with_both_builtins(self):
        self.application.controller.save_environment("custom", {
            "viewport_width": 1000, "viewport_height": 700,
            "device_scale_factor": 1.25, "language": "fr-FR", "touch_mode": True,
        })
        self.application.controller.save_proxy(True, "socks5", "127.0.0.1", 1080)
        application, command = self.open_after_restart()
        for argument in (
            "--window-size=1000,700", "--force-device-scale-factor=1.25",
            "--lang=fr-FR", "--touch-events=enabled", "--proxy-server=socks5://127.0.0.1:1080",
        ):
            self.assertIn(argument, command)
        self.assertIsNone(application.account_service.get_account(self.profile_id))
        deployed_paths = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--load-extension="))
        self.assertEqual({Path(path).name for path in deployed_paths.split(",")}, set(REQUIRED_EXTENSION_NAMES))
        for path in deployed_paths.split(","):
            self.assertTrue(Path(path).is_relative_to(self.workspace.root))
            self.assertTrue((Path(path) / "manifest.json").is_file())

    def test_proxy_off_after_previously_enabled_has_no_proxy_switch(self):
        self.application.controller.save_proxy(True, "http", "127.0.0.1", 8080)
        self.application.controller.save_proxy(False)
        _, command = self.open_after_restart()
        self.assertFalse(any(arg.startswith("--proxy-") for arg in command))

    def test_each_supported_proxy_scheme_survives_persistence_into_real_plan(self):
        for scheme in ("http", "https", "socks4", "socks5"):
            with self.subTest(scheme=scheme):
                self.application.controller.save_proxy(True, scheme, "127.0.0.1", 8080)
                restarted = self.restart()
                directory = restarted.profile_service.require_profile_dir(self.profile_id)
                command = restarted.launcher.build_command(
                    self.profile_id, directory, restarted.profile_service.get_profile_record(self.profile_id),
                )
                self.assertIn(f"--proxy-server={scheme}://127.0.0.1:8080", command)

    def test_repeated_open_of_live_profile_does_not_redeploy_or_start_process(self):
        application, _ = self.open_after_restart()
        paths = application.extension_service.get_profile_extension_paths(self.profile_id)
        before = {(path / "manifest.json"): (path / "manifest.json").stat().st_mtime_ns for path in paths}
        result = application.controller.open_selected()
        self.assertEqual(result, {"requested": 0, "running": 1, "errors": []})
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in before})

    def test_non_gui_composed_launch_also_deploys_builtins(self):
        self.assertTrue(self.application.launcher.launch_discord(self.profile_id))
        command = self.commands[-1]
        self.assertTrue(any(arg.startswith("--load-extension=") for arg in command))
        self.assertTrue(any(arg.startswith("--disable-extensions-except=") for arg in command))


if __name__ == "__main__":
    unittest.main()
