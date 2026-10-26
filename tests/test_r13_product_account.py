"""R13 account-mode, persistence, and sensitive-value boundary checks."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from compatibility.fixtures import DisposableWorkspace
from revamped.accounts import (
    ACCOUNT_MODE_DEVELOPMENT,
    ACCOUNT_MODE_PRODUCT,
)
from revamped.core import InvalidAccountFormatError, ProfileManagerError
from revamped.gui import TkRevampedApp
from revamped.main import compose, compose_product
from revamped.processes import ChromiumProcessInspector


class PendingProcess:
    def poll(self):
        return None


class R13ProductAccountTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r13-account-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.inspector = ChromiumProcessInspector(process_iter=lambda *_: [])

    def compose(self, *, mode=ACCOUNT_MODE_PRODUCT, process_factory=None):
        if mode == ACCOUNT_MODE_PRODUCT:
            return compose_product(
                self.workspace.root,
                process_inspector=self.inspector,
                process_factory=process_factory,
            )
        return compose(
            self.workspace.root,
            account_mode=mode,
            process_inspector=self.inspector,
            process_factory=process_factory,
        )

    def test_development_mode_is_explicit_and_product_setter_is_not_available(self):
        application = self.compose(mode=ACCOUNT_MODE_DEVELOPMENT)
        self.assertEqual(application.account_mode, ACCOUNT_MODE_DEVELOPMENT)
        self.assertEqual(application.account_service.account_mode, ACCOUNT_MODE_DEVELOPMENT)
        profile_id = application.profile_service.create_profile("Synthetic")

        with self.assertRaises(InvalidAccountFormatError):
            application.account_service.set_account(
                profile_id, "normal@example.com:synthetic-password"
            )
        with self.assertRaisesRegex(ProfileManagerError, "Interactive Product Mode"):
            application.account_service.set_product_account(
                profile_id, "normal@example.com", "Product"
            )

    def test_product_mode_accepts_safe_metadata_and_survives_restart(self):
        application = self.compose()
        profile_id = application.profile_service.create_profile("Product")

        account = application.account_service.set_product_account(
            profile_id, "normal@example.com", "Primary account"
        )

        self.assertEqual(account, {
            "mode": ACCOUNT_MODE_PRODUCT,
            "email": "normal@example.com",
            "label": "Primary account",
        })
        catalog = json.loads(application.paths.profiles_json.read_text(encoding="utf-8"))
        record = catalog["profiles"][0]
        self.assertEqual(record["account"], {
            "mode": ACCOUNT_MODE_PRODUCT,
            "email": "normal@example.com",
            "label": "Primary account",
        })

        restarted = self.compose()
        self.assertEqual(restarted.account_service.get_account(profile_id), account)

    def test_product_mode_rejects_credential_shaped_input_without_persisting_it(self):
        application = self.compose()
        profile_id = application.profile_service.create_profile("Product")
        secret = "do-not-write-this-password"

        with self.assertRaises(InvalidAccountFormatError):
            application.account_service.set_account(
                profile_id, f"normal@example.com:{secret}:SYNTHETIC-TOTP"
            )
        with self.assertRaises(InvalidAccountFormatError):
            application.account_service.set_product_account(
                profile_id, "normal@example.com", "Primary", password=secret
            )

        for path in (
            application.paths.profiles_json,
            application.paths.extension_policy_json,
        ):
            if path.exists():
                self.assertNotIn(secret, path.read_text(encoding="utf-8"))
        if application.paths.log_dir.exists():
            for path in application.paths.log_dir.rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret, path.read_text(encoding="utf-8"))

    def test_product_account_launches_with_both_required_extensions(self):
        commands = []

        def record(command, **_kwargs):
            commands.append(command)
            return PendingProcess()

        application = self.compose(process_factory=record)
        profile_id = application.profile_service.create_profile("Product")
        application.account_service.set_product_account(
            profile_id, "normal@example.com", "Primary"
        )

        self.assertTrue(application.launcher.launch_discord(profile_id))
        load = next(argument for argument in commands[-1] if argument.startswith("--load-extension="))
        self.assertEqual(
            {Path(item).name for item in load.split("=", 1)[1].split(",")},
            {"discord-autofill-extension"},
        )
        config = (
            application.extension_service.profile_extension_path(profile_id) / "config.js"
        )
        self.assertNotIn("normal@example.com", config.read_text(encoding="utf-8"))

    def test_removing_account_keeps_chromium_profile_and_deleting_profile_removes_only_association_with_profile(self):
        application = self.compose()
        profile_id = application.profile_service.create_profile("Product")
        profile_dir = application.profile_service.get_profile_dir(profile_id)
        application.account_service.set_product_account(
            profile_id, "normal@example.com", "Primary"
        )

        application.account_service.remove_account(profile_id)
        self.assertTrue(profile_dir.is_dir())
        self.assertIsNone(application.account_service.get_account(profile_id))
        catalog = json.loads(application.paths.profiles_json.read_text(encoding="utf-8"))
        self.assertNotIn("account", catalog["profiles"][0])

        application.account_service.set_product_account(
            profile_id, "normal@example.com", "Primary"
        )
        application.profile_service.delete_profile(profile_id)
        self.assertFalse(profile_dir.exists())
        catalog = json.loads(application.paths.profiles_json.read_text(encoding="utf-8"))
        self.assertEqual(catalog["profiles"], [])

    def test_product_gui_controller_exposes_masked_safe_account_view(self):
        application = self.compose()
        profile_id = application.controller.create_profile("Product")
        application.controller.set_selection([profile_id])
        application.controller.set_product_account("normal@example.com", "Primary")

        data = application.controller.account_dialog_data()
        self.assertEqual(data["mode"], ACCOUNT_MODE_PRODUCT)
        self.assertEqual(data["label"], "Primary")
        self.assertEqual(data["email"], "no****@example.com")
        self.assertNotIn("password", repr(data).casefold())
        self.assertNotIn("totp", repr(data).casefold())

    def test_gui_mode_banner_is_explicit_for_product_mode(self):
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.controller = Mock(account_mode=ACCOUNT_MODE_PRODUCT)

        self.assertIn("Interactive Product Mode", app._account_mode_text())
        self.assertIn("not stored", app._account_mode_text())


if __name__ == "__main__":
    unittest.main()
