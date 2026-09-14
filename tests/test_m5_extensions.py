"""M5 extension architecture regressions using synthetic account data only."""

import shutil
import unittest
from unittest.mock import patch

import test_m1_runtime as m1


class ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    setUp = m1.RuntimeTests.setUp
    cleanup_workspace = m1.RuntimeTests.cleanup_workspace
    make_runtime = m1.RuntimeTests.make_runtime
    make_profiles = m1.RuntimeTests.make_profiles

    def make_source(self):
        self.make_autofill_source()
        (self.manager.EXT_DIR / "shared.js").write_text("const SHARED = 'v1';", encoding="utf-8")

    def make_autofill_source(self):
        source = self.manager.EXT_DIR
        source.mkdir(parents=True)
        (source / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
        (source / "config.js").write_text(
            'const ACCOUNT = {email: "", password: "", totpSecret: ""};',
            encoding="utf-8",
        )

    def test_extension_source_discovery_returns_only_supported_source(self):
        self.make_source()
        profiles = self.make_profiles()

        discovered = self.manager.ExtensionManager(profiles).discover_sources()

        self.assertEqual(discovered, {
            self.manager.AUTOFILL_EXTENSION_NAME: self.manager.EXT_DIR,
        })

    def test_one_profile_deploys_and_loads_extension(self):
        self.make_runtime()
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("One")
        accounts = self.manager.AccountManager(profiles)

        accounts.set_account(profile_id, "one@example.invalid:synthetic-one")
        extension = self.manager.ExtensionManager(profiles).get_profile_extension_paths(profile_id)
        self.assertEqual(len(extension), 1)
        self.assertTrue((extension[0] / "manifest.json").is_file())
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id, extension))
        self.assertTrue(any(
            argument == "--load-extension=" + str(extension[0])
            for argument in self.popen.call_args.args[0]
        ))

    def test_multiple_profiles_keep_extension_configuration_isolated(self):
        self.make_source()
        profiles = self.make_profiles()
        first = profiles.create_profile("First")
        second = profiles.create_profile("Second")
        accounts = self.manager.AccountManager(profiles)

        accounts.set_account(first, "first@example.invalid:synthetic-first:aaaa")
        accounts.set_account(second, "second@example.invalid:synthetic-second:bbbb")

        first_config = accounts._get_config_path(first).read_text(encoding="utf-8")
        second_config = accounts._get_config_path(second).read_text(encoding="utf-8")
        self.assertIn("first@example.invalid", first_config)
        self.assertNotIn("second@example.invalid", first_config)
        self.assertIn("second@example.invalid", second_config)
        self.assertNotIn("first@example.invalid", second_config)
        self.assertEqual(accounts.get_account(first)["password"], "synthetic-first")
        self.assertEqual(accounts.get_account(second)["password"], "synthetic-second")
        self.assertEqual(
            (self.manager.EXT_DIR / "config.js").read_text(encoding="utf-8"),
            'const ACCOUNT = {email: "", password: "", totpSecret: ""};',
        )

    def test_profile_reopen_preserves_account_and_deployment(self):
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Reopen")
        self.manager.AccountManager(profiles).set_account(
            profile_id, "reopen@example.invalid:synthetic-reopen"
        )

        restarted_profiles = self.manager.ProfileManager()
        restarted_accounts = self.manager.AccountManager(restarted_profiles)
        self.assertEqual(
            restarted_accounts.get_account(profile_id)["email"],
            "reopen@example.invalid",
        )
        self.assertEqual(
            len(self.manager.ExtensionManager(restarted_profiles).get_profile_extension_paths(profile_id)),
            1,
        )

    def test_application_restart_can_open_existing_deployment(self):
        self.make_runtime()
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Restart")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(profile_id, "restart@example.invalid:synthetic-restart")

        restarted_launcher = self.manager.ChromiumLauncher()
        restarted_profiles = self.manager.ProfileManager()
        paths = self.manager.ExtensionManager(restarted_profiles).get_profile_extension_paths(profile_id)

        self.assertTrue(restarted_launcher.launch_discord(profile_id, paths))
        self.assertEqual(self.popen.call_args.args[0][-1], "--load-extension=" + str(paths[0]))

    def test_missing_source_reports_error_without_creating_deployment(self):
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Missing source")
        accounts = self.manager.AccountManager(profiles)

        with self.assertRaises(self.manager.ExtensionNotFoundError):
            accounts.set_account(profile_id, "missing@example.invalid:synthetic-missing")
        self.assertFalse(
            (profiles.get_profile_dir(profile_id) / "Unpacked Extensions" /
             self.manager.AUTOFILL_EXTENSION_NAME).exists()
        )

    def test_malformed_or_incomplete_source_is_rejected(self):
        source = self.manager.EXT_DIR
        source.mkdir(parents=True)
        (source / "manifest.json").write_text("{broken", encoding="utf-8")
        (source / "config.js").write_text("const ACCOUNT = {};", encoding="utf-8")
        profiles = self.make_profiles()

        with self.assertRaises(self.manager.ExtensionError):
            self.manager.ExtensionManager(profiles).discover_sources()

        (source / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
        (source / "config.js").unlink()
        with self.assertRaises(self.manager.ExtensionError):
            self.manager.ExtensionManager(profiles).discover_sources()

    def test_missing_profile_deployment_can_be_recreated(self):
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Re-deploy")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(profile_id, "redeploy@example.invalid:synthetic-redeploy")
        deployment = profiles.get_profile_dir(profile_id) / "Unpacked Extensions" / self.manager.AUTOFILL_EXTENSION_NAME
        shutil.rmtree(deployment)

        recreated = accounts._ensure_extension_installed(profile_id)

        self.assertEqual(recreated, deployment)
        self.assertTrue((deployment / "manifest.json").is_file())
        self.assertEqual(accounts.get_account(profile_id), None)

    def test_stale_deployment_refresh_preserves_profile_config(self):
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Stale")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(profile_id, "stale@example.invalid:synthetic-stale")
        config_before = accounts._get_config_path(profile_id).read_bytes()
        (self.manager.EXT_DIR / "shared.js").write_text("const SHARED = 'v2';", encoding="utf-8")

        accounts._ensure_extension_installed(profile_id)

        self.assertEqual(accounts._get_config_path(profile_id).read_bytes(), config_before)
        self.assertEqual(
            (profiles.get_profile_dir(profile_id) / "Unpacked Extensions" /
             self.manager.AUTOFILL_EXTENSION_NAME / "shared.js").read_text(encoding="utf-8"),
            "const SHARED = 'v2';",
        )

    def test_deployment_failure_leaves_existing_config_and_no_staging_copy(self):
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Deployment failure")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(profile_id, "failure@example.invalid:synthetic-failure")
        config_before = accounts._get_config_path(profile_id).read_bytes()

        with patch.object(self.manager.shutil, "copytree", side_effect=OSError("synthetic deployment failure")):
            with self.assertRaises(self.manager.ExtensionDeploymentError):
                accounts._ensure_extension_installed(profile_id)

        self.assertEqual(accounts._get_config_path(profile_id).read_bytes(), config_before)
        extension_parent = profiles.get_profile_dir(profile_id) / "Unpacked Extensions"
        self.assertEqual(list(extension_parent.glob(".*staging-*")), [])
        self.assertEqual(list(extension_parent.glob(".*backup-*")), [])

    def test_invalid_optional_deployment_is_skipped_during_launch(self):
        self.make_runtime()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Broken deployment")
        deployment = profiles.get_profile_dir(profile_id) / "Unpacked Extensions" / self.manager.AUTOFILL_EXTENSION_NAME
        deployment.mkdir(parents=True)
        (deployment / "manifest.json").write_text("{broken", encoding="utf-8")
        (deployment / "config.js").write_text("const ACCOUNT = {};", encoding="utf-8")

        paths = self.manager.ExtensionManager(profiles).get_profile_extension_paths(profile_id)
        self.assertEqual(paths, [])
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id, paths))
        self.assertFalse(any(argument.startswith("--load-extension=")
                             for argument in self.popen.call_args.args[0]))

    def test_existing_deployment_remains_loadable_when_source_is_missing(self):
        self.make_runtime()
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Source removed")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(profile_id, "source@example.invalid:synthetic-source")
        shutil.rmtree(self.manager.EXT_DIR)

        paths = self.manager.ExtensionManager(self.manager.ProfileManager()).get_profile_extension_paths(profile_id)
        self.assertEqual(len(paths), 1)
        self.assertTrue(self.manager.ChromiumLauncher().launch_discord(profile_id, paths))

    def test_import_still_assigns_one_account_config_per_profile(self):
        self.make_source()
        profiles = self.make_profiles()
        import_file = self.work / "m5-accounts.txt"
        import_file.write_text(
            "import-one@example.invalid:synthetic-one\n"
            "import-two@example.invalid:synthetic-two\n",
            encoding="utf-8",
        )
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.profile_manager = profiles
        app.account_manager = self.manager.AccountManager(profiles)
        app.profiles = []
        app.refresh_list = lambda: None

        with patch.object(self.manager.filedialog, "askopenfilename", return_value=str(import_file)), \
                patch.object(self.manager.messagebox, "showinfo"), \
                patch.object(self.manager.messagebox, "showerror") as showerror:
            app.bulk_import_profiles()

        showerror.assert_not_called()
        records = profiles.get_profiles()
        self.assertEqual(len(records), 2)
        self.assertEqual(
            {app.account_manager.get_account(profile_id)["email"] for profile_id, _ in records},
            {"import-one@example.invalid", "import-two@example.invalid"},
        )
        self.assertEqual(
            len({
                str(path.parent.parent)
                for profile_id, _ in records
                for path in self.manager.ExtensionManager(profiles).get_profile_extension_paths(profile_id)
            }),
            2,
        )

    def test_only_autofill_extension_is_discovered_and_logs_do_not_contain_accounts(self):
        self.make_source()
        profiles = self.make_profiles()
        profile_id = profiles.create_profile("Log hygiene")
        secret_values = ["log@example.invalid", "synthetic-log-password", "SYNTHETICLOG"]
        self.manager.AccountManager(profiles).set_account(
            profile_id, ":".join(secret_values)
        )

        self.assertEqual(
            set(self.manager.ExtensionManager(profiles).discover_sources()),
            {self.manager.AUTOFILL_EXTENSION_NAME},
        )
        log_text = repr(self.manager.logger.mock_calls)
        for value in secret_values:
            self.assertNotIn(value, log_text)


if __name__ == "__main__":
    unittest.main()
