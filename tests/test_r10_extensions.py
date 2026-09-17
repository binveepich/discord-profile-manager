"""R10 extension registry/deployment/command checks with disposable profiles."""

import hashlib
import json
from pathlib import Path
import unittest

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT
from revamped.core import ExtensionError, ExtensionNotFoundError, ProjectPaths
from revamped.extensions import ExtensionService, REQUIRED_EXTENSION_NAMES
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
        self.make_source(paths, REQUIRED_EXTENSION_NAMES[0])

        with self.assertRaisesRegex(ExtensionNotFoundError, REQUIRED_EXTENSION_NAMES[1]):
            extensions.ensure_required_extensions(profile_id)

        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])
        self.assertEqual(list((profiles.require_profile_dir(profile_id) / "Unpacked Extensions").iterdir()), [])

    def test_invalid_required_registry_source_is_not_silently_omitted(self):
        paths, _, profile_id, extensions, _ = self.make_bundle()
        for name in REQUIRED_EXTENSION_NAMES:
            self.make_source(paths, name)
        (paths.extensions_dir / REQUIRED_EXTENSION_NAMES[1] / "manifest.json").write_text(
            "{broken", encoding="utf-8"
        )

        with self.assertRaisesRegex(ExtensionError, REQUIRED_EXTENSION_NAMES[1]):
            extensions.ensure_required_extensions(profile_id)

        self.assertEqual(extensions.get_profile_extension_paths(profile_id), [])

    def test_manifest_with_missing_required_script_fails_before_launch(self):
        paths, _, profile_id, extensions, _ = self.make_bundle()
        for name in REQUIRED_EXTENSION_NAMES:
            self.make_source(paths, name)
        (paths.extensions_dir / REQUIRED_EXTENSION_NAMES[1] / "manifest.json").write_text(
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
        (deployed[1] / "manifest.json").write_text("{broken", encoding="utf-8")

        refreshed = extensions.ensure_required_extensions(profile_id)

        self.assertEqual(refreshed, deployed)
        self.assertEqual(
            json.loads((refreshed[1] / "manifest.json").read_text(encoding="utf-8"))["manifest_version"],
            3,
        )


if __name__ == "__main__":
    unittest.main()
