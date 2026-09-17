"""R12 global extension policy and launch filtering checks."""

import hashlib
import inspect
import json
from pathlib import Path
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ExtensionError, ProjectPaths
from revamped.extensions import (
    ExtensionService,
    REQUIRED_EXTENSION_NAMES,
)
from revamped.gui import TkRevampedApp
from revamped.launcher import ChromiumLauncher
from revamped.processes import ChromiumProcessInspector
from revamped.profiles import ProfileService


class PendingProcess:
    def poll(self):
        return None


class R12GlobalExtensionTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r12-extensions-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.paths = ProjectPaths(self.workspace.root)
        self.inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        self.runtime = self.workspace.root / "runtime" / "chrome.exe"
        self.runtime.parent.mkdir(parents=True)
        self.runtime.write_bytes(b"synthetic runtime")
        for name in REQUIRED_EXTENSION_NAMES:
            self.make_extension(name, name.replace("-extension", "").title())
        self.make_extension("future-extension", "Future Extension")
        self.profiles = ProfileService(self.paths, process_inspector=self.inspector)
        self.extensions = ExtensionService(self.paths, self.profiles)

    def make_extension(self, name, display_name):
        source = self.paths.extensions_dir / name
        source.mkdir(parents=True, exist_ok=True)
        (source / "manifest.json").write_text(
            json.dumps({
                "manifest_version": 3,
                "name": display_name,
                "version": "1.0",
            }),
            encoding="utf-8",
        )
        if name == REQUIRED_EXTENSION_NAMES[0]:
            (source / "config.js").write_text(
                'const ACCOUNT = {email: "", password: "", totpSecret: ""};',
                encoding="utf-8",
            )
        return source

    def new_launcher(self, extension_service=None):
        commands = []

        def record(command, **_kwargs):
            commands.append(command)
            return PendingProcess()

        launcher = ChromiumLauncher(
            self.paths,
            self.profiles,
            extension_service=extension_service,
            process_inspector=self.inspector,
            process_factory=record,
        )
        launcher.launcher_path = self.runtime
        return launcher, commands

    @staticmethod
    def source_hashes(root):
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(root).rglob("*")
            if path.is_file()
        }

    def test_required_builtins_are_enabled_and_locked(self):
        state = self.extensions.get_registry_state()

        self.assertEqual(
            [item["name"] for item in state["built_ins"]],
            list(REQUIRED_EXTENSION_NAMES),
        )
        self.assertTrue(all(item["enabled"] and item["required"] for item in state["built_ins"]))
        self.assertEqual(
            set(state["policy"]["enabled_extensions"]),
            set(REQUIRED_EXTENSION_NAMES),
        )
        with self.assertRaisesRegex(ExtensionError, "cannot be disabled"):
            self.extensions.disable_extension(REQUIRED_EXTENSION_NAMES[0])
        self.assertTrue(self.extensions.is_extension_enabled(REQUIRED_EXTENSION_NAMES[0]))

    def test_optional_extensions_can_be_enabled_disabled_and_persisted(self):
        self.assertFalse(self.extensions.is_extension_enabled("future-extension"))
        enabled = self.extensions.enable_extension("future-extension")
        self.assertTrue(next(item for item in enabled["optional"] if item["name"] == "future-extension")["enabled"])
        self.assertIn("future-extension", json.loads(
            self.paths.extension_policy_json.read_text(encoding="utf-8")
        )["enabled_extensions"])

        restarted_profiles = ProfileService(self.paths, process_inspector=self.inspector)
        restarted = ExtensionService(self.paths, restarted_profiles)
        self.assertTrue(restarted.is_extension_enabled("future-extension"))
        disabled = restarted.disable_extension("future-extension")
        self.assertFalse(next(item for item in disabled["optional"] if item["name"] == "future-extension")["enabled"])
        restarted_again = ExtensionService(
            self.paths,
            ProfileService(self.paths, process_inspector=self.inspector),
        )
        self.assertFalse(restarted_again.is_extension_enabled("future-extension"))

    def test_new_and_existing_profiles_follow_current_policy_on_future_launches(self):
        existing = self.profiles.create_profile("Existing")
        self.extensions.enable_extension("future-extension")
        new_profile = self.profiles.create_profile("New")
        launcher, commands = self.new_launcher(self.extensions)
        self.assertTrue(launcher.launch_discord(existing))
        self.assertEqual(len(commands), 1)
        self.assertTrue(any("future-extension" in argument for argument in commands[-1]))

        # A fresh launcher represents the next launch after Chromium closes.
        self.extensions.disable_extension("future-extension")
        launcher, commands = self.new_launcher(self.extensions)
        self.assertTrue(launcher.launch_discord(new_profile))
        self.assertFalse(any("future-extension" in argument for argument in commands[-1]))

        self.extensions.enable_extension("future-extension")
        launcher, commands = self.new_launcher(self.extensions)
        self.assertTrue(launcher.launch_discord(existing))
        self.assertTrue(any("future-extension" in argument for argument in commands[-1]))

    def test_launch_arguments_contain_required_only_when_optional_is_disabled(self):
        profile_id = self.profiles.create_profile("Launch filtering")
        source_snapshot = self.source_hashes(self.paths.extensions_dir)
        self.extensions.enable_extension("future-extension")
        launcher, commands = self.new_launcher(self.extensions)
        launcher.launch_discord(profile_id)
        enabled_load = next(
            argument.split("=", 1)[1]
            for argument in commands[-1]
            if argument.startswith("--load-extension=")
        )
        self.assertEqual(
            {Path(path).name for path in enabled_load.split(",")},
            {*REQUIRED_EXTENSION_NAMES, "future-extension"},
        )

        self.extensions.disable_extension("future-extension")
        launcher, commands = self.new_launcher(self.extensions)
        launcher.launch_discord(profile_id)
        disabled_load = next(
            argument.split("=", 1)[1]
            for argument in commands[-1]
            if argument.startswith("--load-extension=")
        )
        self.assertEqual(
            {Path(path).name for path in disabled_load.split(",")},
            set(REQUIRED_EXTENSION_NAMES),
        )
        direct_command = launcher.build_command(
            profile_id,
            self.profiles.require_profile_dir(profile_id),
            self.profiles.get_profile_record(profile_id),
            self.extensions.get_profile_extension_paths(profile_id),
        )
        direct_load = next(
            argument.split("=", 1)[1]
            for argument in direct_command
            if argument.startswith("--load-extension=")
        )
        self.assertEqual(
            {Path(path).name for path in direct_load.split(",")},
            set(REQUIRED_EXTENSION_NAMES),
        )
        self.assertEqual(source_snapshot, self.source_hashes(self.paths.extensions_dir))

    def test_valid_future_extensions_are_discovered_without_code_changes(self):
        self.make_extension("another-future-extension", "Another Future Extension")
        names = [item["name"] for item in self.extensions.discover_extensions()]
        self.assertIn("another-future-extension", names)
        optional = {
            item["name"]: item for item in self.extensions.get_registry_state()["optional"]
        }
        self.assertFalse(optional["another-future-extension"]["enabled"])

    def test_corrupt_policy_falls_back_to_required_builtins_without_overwriting_it(self):
        corrupt = b"{not-json"
        self.paths.extension_policy_json.parent.mkdir(parents=True)
        self.paths.extension_policy_json.write_bytes(corrupt)

        state = self.extensions.get_registry_state()

        self.assertEqual(
            set(state["policy"]["enabled_extensions"]),
            set(REQUIRED_EXTENSION_NAMES),
        )
        self.assertEqual(self.paths.extension_policy_json.read_bytes(), corrupt)

    def test_visible_gui_exposes_global_extension_manager(self):
        source = inspect.getsource(TkRevampedApp._build_widgets)
        manager = inspect.getsource(TkRevampedApp.manage_extensions)
        self.assertIn('"extensions"', source)
        self.assertIn("Extensions...", source)
        self.assertIn("Refresh Registry", manager)
        self.assertIn('text="Enable"', manager)
        self.assertIn('text="Disable"', manager)
        self.assertIn('Required"', manager)


if __name__ == "__main__":
    unittest.main()
