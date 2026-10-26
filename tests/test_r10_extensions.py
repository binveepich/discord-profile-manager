"""R10 extension registry/deployment/command checks with disposable profiles."""

import hashlib
import json
from pathlib import Path
import shutil
import unittest

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT
from revamped.core import ExtensionError, ExtensionNotFoundError, ProjectPaths
from revamped.extensions import (
    AUTOFILL_EXTENSION_NAME,
    ExtensionService,
    REQUIRED_EXTENSION_NAMES,
    TOKEN_EXTRACTOR_EXTENSION_NAME,
)
from revamped.launcher import ChromiumLauncher
from revamped.processes import ChromiumProcessInspector
from revamped.profiles import ProfileService


class R10ExtensionIntegrationTests(unittest.TestCase):
    def make_bundle(self, *, repository_assets=False):
        workspace = DisposableWorkspace("r10-extensions-")
        workspace.__enter__()
        self.addCleanup(workspace.__exit__, None, None, None)
        paths = ProjectPaths(
            workspace.root,
            assets_root=PROJECT_ROOT if repository_assets else workspace.root,
        )
        inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        profiles = ProfileService(paths, process_inspector=inspector)
        profile_id = profiles.create_profile("Disposable R10 extension check")
        extensions = ExtensionService(paths, profiles)
        launcher = ChromiumLauncher(paths, profiles, process_inspector=inspector)
        return paths, profiles, profile_id, extensions, launcher

    @staticmethod
    def make_source(paths, name):
        source = paths.extensions_dir / name
        source.mkdir(parents=True)
        (source / "manifest.json").write_text(
            json.dumps({"manifest_version": 3}), encoding="utf-8"
        )
        if name == REQUIRED_EXTENSION_NAMES[0]:
            (source / "config.js").write_text(
                'const ACCOUNT = {email: "", password: "", totpSecret: ""};',
                encoding="utf-8",
            )
        return source

    @staticmethod
    def tree_hashes(root):
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(root).rglob("*")
            if path.is_file()
        }

    def test_missing_required_registry_source_fails_before_any_deployment(self):
        paths, profiles, profile_id, extensions, _ = self.make_bundle()
        with self.assertRaisesRegex(ExtensionNotFoundError, REQUIRED_EXTENSION_NAMES[0]):
            extensions.ensure_required_extensions(profile_id)

        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])
        self.assertEqual(list((profiles.require_profile_dir(profile_id) / "Unpacked Extensions").iterdir()), [])

    def test_invalid_required_registry_source_is_not_silently_omitted(self):
        paths, _, profile_id, extensions, _ = self.make_bundle()
        self.make_source(paths, REQUIRED_EXTENSION_NAMES[0])
        (paths.extensions_dir / REQUIRED_EXTENSION_NAMES[0] / "manifest.json").write_text(
            "{broken", encoding="utf-8"
        )

        with self.assertRaisesRegex(ExtensionError, REQUIRED_EXTENSION_NAMES[0]):
            extensions.ensure_required_extensions(profile_id)

        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])

    def test_manifest_with_missing_required_script_fails_before_launch(self):
        paths, _, profile_id, extensions, _ = self.make_bundle()
        self.make_source(paths, REQUIRED_EXTENSION_NAMES[0])
        (paths.extensions_dir / REQUIRED_EXTENSION_NAMES[0] / "manifest.json").write_text(
            json.dumps({
                "manifest_version": 3,
                "background": {"service_worker": "missing.js"},
            }),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ExtensionError, "missing.js"):
            extensions.ensure_required_extensions(profile_id)

        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])

    def test_repository_registry_builtins_reach_real_command_without_account_setup(self):
        paths, profiles, profile_id, extensions, launcher = self.make_bundle(repository_assets=True)
        hashes_before = self.tree_hashes(paths.extensions_dir)
        profile_dir = profiles.require_profile_dir(profile_id)
        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])

        deployed = extensions.ensure_required_extensions(profile_id)
        command = launcher.build_command(
            profile_id, profile_dir, profiles.get_profile_record(profile_id), deployed
        )

        self.assertEqual([path.name for path in deployed], list(REQUIRED_EXTENSION_NAMES))
        joined = ",".join(str(path) for path in deployed)
        self.assertIn(f"--load-extension={joined}", command)
        self.assertIn(f"--disable-extensions-except={joined}", command)
        self.assertEqual(command[0], str(PROJECT_ROOT / "browser" / "chrome.exe"))
        self.assertIn(f"--user-data-dir={profile_dir}", command)
        for path in deployed:
            self.assertTrue(path.is_relative_to(paths.root))
            manifest = extensions._validate_extension_directory(path, path.name)
            self.assertTrue(manifest["name"])
            self.assertTrue(manifest["version"])
            self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(self.tree_hashes(paths.extensions_dir), hashes_before)

    def test_invalid_existing_required_deployment_is_repaired_from_registry(self):
        paths, _, profile_id, extensions, _ = self.make_bundle()
        for name in REQUIRED_EXTENSION_NAMES:
            self.make_source(paths, name)
        deployed = extensions.ensure_required_extensions(profile_id)
        (deployed[0] / "manifest.json").write_text("{broken", encoding="utf-8")

        refreshed = extensions.ensure_required_extensions(profile_id)

        self.assertEqual(refreshed, deployed)
        self.assertEqual(
            json.loads((refreshed[0] / "manifest.json").read_text(encoding="utf-8"))["manifest_version"],
            3,
        )

    def test_token_extractor_is_available_optional_and_not_deployed_to_fresh_profile(self):
        paths, profiles, profile_id, extensions, launcher = self.make_bundle(
            repository_assets=True
        )
        source_hashes = self.tree_hashes(paths.extensions_dir)
        self.assertEqual(REQUIRED_EXTENSION_NAMES, (AUTOFILL_EXTENSION_NAME,))
        state = extensions.get_registry_state()
        optional = next(
            item for item in state["optional"]
            if item["name"] == TOKEN_EXTRACTOR_EXTENSION_NAME
        )
        self.assertTrue(optional["available"])
        self.assertFalse(optional["required"])
        self.assertFalse(optional["enabled"])

        deployed = extensions.ensure_enabled_extensions(profile_id)
        names = {path.name for path in deployed}
        profile_extensions = (
            profiles.require_profile_dir(profile_id) / "Unpacked Extensions"
        )
        command = launcher.build_command(
            profile_id, profiles.require_profile_dir(profile_id),
            profiles.get_profile_record(profile_id), deployed,
        )

        self.assertEqual(names, {AUTOFILL_EXTENSION_NAME})
        self.assertFalse((profile_extensions / TOKEN_EXTRACTOR_EXTENSION_NAME).exists())
        load = next(arg for arg in command if arg.startswith("--load-extension="))
        self.assertEqual(
            {Path(item).name for item in load.split("=", 1)[1].split(",")},
            {AUTOFILL_EXTENSION_NAME},
        )
        self.assertEqual(self.tree_hashes(paths.extensions_dir), source_hashes)

    def test_preexisting_token_extractor_is_loaded_without_refresh_or_cleanup(self):
        paths, profiles, profile_id, extensions, launcher = self.make_bundle(
            repository_assets=True
        )
        source_hashes = self.tree_hashes(paths.extensions_dir)
        profile_extensions = (
            profiles.require_profile_dir(profile_id) / "Unpacked Extensions"
        )
        retained = profile_extensions / TOKEN_EXTRACTOR_EXTENSION_NAME
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(paths.extensions_dir / TOKEN_EXTRACTOR_EXTENSION_NAME, retained)
        autofill = profile_extensions / AUTOFILL_EXTENSION_NAME
        shutil.copytree(paths.extensions_dir / AUTOFILL_EXTENSION_NAME, autofill)
        retained_hashes = self.tree_hashes(retained)
        preferences = profiles.get_browser_profile_dir(profile_id) / "Preferences"
        preferences.parent.mkdir(parents=True, exist_ok=True)
        token_manifest = json.loads(
            (retained / "manifest.json").read_text(encoding="utf-8")
        )
        autofill_manifest = json.loads(
            (autofill / "manifest.json").read_text(encoding="utf-8")
        )
        token_id = extensions._extension_id(token_manifest)
        autofill_id = extensions._extension_id(autofill_manifest)
        token_registration = {
            "location": 4,
            "manifest": token_manifest,
            "path": str(retained),
            "state": 1,
        }
        autofill_registration = {
            "location": 4,
            "manifest": autofill_manifest,
            "path": str(autofill),
            "state": 1,
        }
        preferences.write_text(json.dumps({
            "extensions": {"settings": {
                token_id: token_registration,
                autofill_id: autofill_registration,
            }},
            "toolbar": {"pinned_actions": [token_id, autofill_id]},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        preferences_before = preferences.read_bytes()

        deployed = extensions.ensure_enabled_extensions(profile_id)
        command = launcher.build_command(
            profile_id, profiles.require_profile_dir(profile_id),
            profiles.get_profile_record(profile_id), deployed,
        )
        load = next(arg for arg in command if arg.startswith("--load-extension="))

        self.assertIn(retained, deployed)
        self.assertIn(TOKEN_EXTRACTOR_EXTENSION_NAME, load)
        self.assertEqual(self.tree_hashes(retained), retained_hashes)
        preferences_after = json.loads(preferences.read_text(encoding="utf-8"))
        self.assertEqual(
            preferences_after["extensions"]["settings"][token_id],
            token_registration,
        )
        self.assertIn(token_id, preferences_after["toolbar"]["pinned_actions"])
        self.assertEqual(preferences.read_bytes(), preferences_before)
        self.assertEqual(self.tree_hashes(paths.extensions_dir), source_hashes)

    def test_legacy_required_policy_migrates_extractor_to_default_off(self):
        paths, profiles, profile_id, extensions, _ = self.make_bundle(
            repository_assets=True
        )
        policy_file = paths.extension_policy_json
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_policy = json.dumps({
            "version": 1,
            "enabled_extensions": [
                AUTOFILL_EXTENSION_NAME,
                TOKEN_EXTRACTOR_EXTENSION_NAME,
            ],
        }).encode("utf-8")
        policy_file.write_bytes(legacy_policy)

        state = extensions.get_registry_state()
        optional = next(
            item for item in state["optional"]
            if item["name"] == TOKEN_EXTRACTOR_EXTENSION_NAME
        )
        deployed = extensions.ensure_enabled_extensions(profile_id)

        self.assertFalse(optional["enabled"])
        self.assertEqual({path.name for path in deployed}, {AUTOFILL_EXTENSION_NAME})
        self.assertFalse(
            (profiles.require_profile_dir(profile_id) / "Unpacked Extensions"
             / TOKEN_EXTRACTOR_EXTENSION_NAME).exists()
        )
        self.assertEqual(policy_file.read_bytes(), legacy_policy)

        extensions.enable_extension(TOKEN_EXTRACTOR_EXTENSION_NAME)
        policy = json.loads(policy_file.read_text(encoding="utf-8"))
        self.assertEqual(policy["version"], 2)
        self.assertIn(TOKEN_EXTRACTOR_EXTENSION_NAME, policy["enabled_extensions"])
        self.assertNotIn(TOKEN_EXTRACTOR_EXTENSION_NAME, policy["disabled_extensions"])
        deliberately_deployed = extensions.ensure_enabled_extensions(profile_id)
        self.assertIn(
            TOKEN_EXTRACTOR_EXTENSION_NAME,
            {path.name for path in deliberately_deployed},
        )


if __name__ == "__main__":
    unittest.main()
