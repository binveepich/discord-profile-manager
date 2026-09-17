"""R6 extension/account compatibility tests with synthetic data only."""

from contextlib import contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from compatibility.fixtures import DisposableWorkspace
from revamped.accounts import AccountCompatibilityService
from revamped.core import ExtensionDeploymentError, ExtensionError, ExtensionNotFoundError, ProjectPaths, ProfileManagerError
from revamped.extensions import ExtensionService


class FakeProfileService:
    def __init__(self, path):
        self.path = path
        self.record = {"profile_id": "profile_0001", "proxy_enabled": False}

    @contextmanager
    def operation(self):
        yield

    def require_profile_dir(self, profile_id):
        if profile_id != self.record["profile_id"]:
            raise ProfileManagerError("missing profile")
        return self.path

    def get_profile_dir(self, profile_id):
        return self.path

    def get_browser_profile_dir(self, profile_id):
        return self.path / "Default"


class R6Tests(unittest.TestCase):
    def make_bundle(self):
        workspace = DisposableWorkspace("r6-")
        workspace.__enter__()
        self.addCleanup(workspace.__exit__, None, None, None)
        paths = ProjectPaths(workspace.root)
        profile = paths.profiles_dir / "profile_0001"
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        source = paths.autofill_extension_dir
        source.mkdir(parents=True)
        (source / "manifest.json").write_text(json.dumps({"manifest_version": 3}), encoding="utf-8")
        (source / "config.js").write_text('const ACCOUNT = {email: "", password: "", totpSecret: ""};', encoding="utf-8")
        (source / "shared.js").write_text("v1", encoding="utf-8")
        self.add_extension(
            paths,
            "discord-token-extractor-extension",
            {"manifest_version": 3, "background": {"service_worker": "background.js"}},
            {"background.js": "const SOURCE = true;"},
        )
        service = FakeProfileService(profile)
        extensions = ExtensionService(paths, service)
        accounts = AccountCompatibilityService(paths, service, extensions)
        return paths, profile, service, extensions, accounts

    def add_extension(self, paths, name, manifest, files=None):
        source = paths.extensions_dir / name
        source.mkdir(parents=True, exist_ok=True)
        (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for relative_name, contents in (files or {}).items():
            target = source / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        return source

    def test_extension_source_validation_and_staged_deployment(self):
        _, profile, _, extensions, _ = self.make_bundle()
        target = extensions.ensure_profile_extension("profile_0001")
        self.assertTrue((target / "manifest.json").is_file())
        self.assertEqual((target / "shared.js").read_text(encoding="utf-8"), "v1")

    def test_registry_discovers_multiple_extensions_and_future_extension(self):
        paths, _, _, extensions, _ = self.make_bundle()
        self.add_extension(
            paths,
            "discord-token-extractor-extension",
            {"manifest_version": 3, "background": {"service_worker": "background.js"}},
            {"background.js": "self.addEventListener('install', () => {});"},
        )
        self.add_extension(paths, "future-extension", {"manifest_version": 3})
        (paths.extensions_dir / "ignored-directory").mkdir()

        discovered = extensions.discover_sources()

        self.assertEqual(
            list(discovered),
            ["discord-autofill-extension", "discord-token-extractor-extension", "future-extension"],
        )

    def test_required_deployment_keeps_profiles_and_source_registry_isolated(self):
        paths, first_profile, service, extensions, _ = self.make_bundle()
        self.add_extension(
            paths,
            "discord-token-extractor-extension",
            {"manifest_version": 3, "background": {"service_worker": "background.js"}},
            {"background.js": "const SOURCE = true;"},
        )
        second_profile = paths.profiles_dir / "profile_0002"
        (second_profile / "Default").mkdir(parents=True)
        (second_profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        first_paths = extensions.ensure_required_extensions("profile_0001")

        second_service = FakeProfileService(second_profile)
        second_service.record = {"profile_id": "profile_0002", "proxy_enabled": False}
        second_extensions = ExtensionService(paths, second_service)
        second_paths = second_extensions.ensure_required_extensions("profile_0002")

        self.assertEqual(
            [path.name for path in first_paths],
            ["discord-autofill-extension", "discord-token-extractor-extension"],
        )
        self.assertEqual(
            [path.name for path in second_paths],
            ["discord-autofill-extension", "discord-token-extractor-extension"],
        )
        (first_paths[1] / "profile-local.fixture").write_text("first", encoding="utf-8")
        self.assertFalse((second_paths[1] / "profile-local.fixture").exists())
        self.assertFalse((paths.extensions_dir / "discord-token-extractor-extension" / "profile-local.fixture").exists())

    def test_refresh_preserves_profile_config_and_unknown_extra_files(self):
        paths, profile, _, extensions, accounts = self.make_bundle()
        accounts.set_account("profile_0001", "one@example.invalid:synthetic-one")
        target = extensions.profile_extension_path("profile_0001")
        extra = target / "profile-local.fixture"
        extra.write_text("keep", encoding="utf-8")
        config_before = (target / "config.js").read_bytes()
        (paths.autofill_extension_dir / "shared.js").write_text("v2", encoding="utf-8")
        extensions.ensure_profile_extension("profile_0001")
        self.assertEqual((target / "config.js").read_bytes(), config_before)
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep")
        self.assertEqual((target / "shared.js").read_text(encoding="utf-8"), "v2")

    def test_invalid_optional_deployment_is_skipped(self):
        _, profile, _, extensions, _ = self.make_bundle()
        target = profile / "Unpacked Extensions" / "discord-autofill-extension"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text("{broken", encoding="utf-8")
        (target / "config.js").write_text("const ACCOUNT = {};", encoding="utf-8")
        self.assertEqual(extensions.get_profile_extension_paths("profile_0001"), [])

    def test_missing_source_and_copy_failure_leave_safe_state(self):
        paths, profile, _, extensions, accounts = self.make_bundle()
        paths.autofill_extension_dir.rename(paths.extensions_dir / "removed")
        with self.assertRaises(ExtensionNotFoundError):
            extensions.ensure_profile_extension("profile_0001")
        (paths.extensions_dir / "removed").rename(paths.autofill_extension_dir)
        with patch("revamped.extensions.shutil.copytree", side_effect=OSError("synthetic")):
            with self.assertRaises(ExtensionDeploymentError):
                extensions.ensure_profile_extension("profile_0001")
        self.assertEqual(list((profile / "Unpacked Extensions").glob(".*staging-*")), [])

    def test_account_compatibility_round_trip_masks_and_hygiene(self):
        paths, profile, service, extensions, accounts = self.make_bundle()
        logger = Mock()
        accounts.logger = logger
        accounts.set_account("profile_0001", " one@example.invalid : synthetic-one : abc123 ")
        account = accounts.get_account("profile_0001")
        self.assertEqual(account, {"email": "one@example.invalid", "password": "synthetic-one", "totp_secret": "ABC123"})
        self.assertEqual(accounts.mask_email(account["email"]), "on*@example.invalid")
        self.assertEqual(accounts.mask_password(account["password"]), "•" * len(account["password"]))
        self.assertNotIn("synthetic-one", repr(logger.mock_calls))
        accounts.remove_account("profile_0001")
        self.assertIsNone(accounts.get_account("profile_0001"))

    def test_account_setup_rejects_missing_source_and_running_profile(self):
        paths, profile, service, extensions, accounts = self.make_bundle()
        paths.autofill_extension_dir.rename(paths.extensions_dir / "removed")
        with self.assertRaises(ExtensionNotFoundError):
            accounts.set_account("profile_0001", "one@example.invalid:synthetic-one")
        paths.extensions_dir.joinpath("removed").rename(paths.autofill_extension_dir)
        process_inspector = Mock()
        process_inspector.using_directory.return_value = True
        accounts.process_inspector = process_inspector
        with self.assertRaises(ProfileManagerError):
            accounts.set_account("profile_0001", "one@example.invalid:synthetic-one")


if __name__ == "__main__":
    unittest.main()
