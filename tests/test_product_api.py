"""Focused tests for the React/pywebview product contract."""

import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from compatibility.fixtures import DisposableWorkspace
from revamped.accounts import derive_profile_name, parse_account_string
from revamped import environment
from revamped.core import InvalidAccountFormatError, ProxyValidationError
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.processes import ChromiumProcessInspector


class ProductAPITests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("product-api-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        self.application = compose_product_candidate(
            self.workspace.root,
            process_inspector=self.inspector,
        )
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)

    def test_account_parser_and_default_name(self):
        parsed = parse_account_string("hello@example.com:fixture-password:abc123")
        self.assertEqual(parsed["email"], "hello@example.com")
        self.assertEqual(parsed["totp_secret"], "ABC123")
        self.assertEqual(derive_profile_name(parsed["email"]), "hello")

    def test_product_dto_hides_credentials_but_explicit_export_includes_them(self):
        secret = "fixture-password"
        row = self.api.create_profile(account_input=f"hello@example.com:{secret}:fixture-totp")
        self.assertEqual(row["stt"], "0001")
        self.assertEqual(row["account"], "hello@example.com")
        dto_text = json.dumps(self.api.list_profiles())
        export_text = self.api.export_json()["content"] + self.api.export_csv()["content"]
        self.assertNotIn(secret, dto_text)
        self.assertNotIn("fixture-totp", dto_text)
        self.assertIn(secret, export_text)
        self.assertIn("FIXTURE-TOTP", export_text)
        staged = self.application.extension_service.profile_extension_path("profile_0001") / "config.js"
        self.assertIn(secret, staged.read_text(encoding="utf-8"))
        self.assertNotIn(secret, self.application.paths.profiles_json.read_text(encoding="utf-8"))

    def test_stt_compacts_without_changing_profile_identity(self):
        first = self.api.create_profile("Alpha")["profile_id"]
        middle = self.api.create_profile("Middle")["profile_id"]
        last = self.api.create_profile("Omega")["profile_id"]
        original_last_dir = self.application.profile_service.get_profile_dir(last)
        self.api.delete_profiles([middle], confirmed=True)
        rows = self.api.list_profiles()
        self.assertEqual([(row["stt"], row["profile_id"]) for row in rows], [
            ("0001", first), ("0002", last)
        ])
        self.assertEqual(self.application.profile_service.get_profile_dir(last), original_last_dir)

    def test_txt_import_uses_auto_environment_and_reports_bad_lines(self):
        result = self.api.import_accounts_txt_sync(
            "one@example.com:fixture-one\nnot-an-account\ntwo@example.com:fixture-two:totp"
        )
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["errors"][0]["line"], 2)
        rows = self.api.list_profiles()
        self.assertEqual({row["environment"]["preset"] for row in rows}, {"auto"})
        self.assertEqual({row["environment"]["label"] for row in rows}, {"Auto"})
        for row in rows:
            record = self.application.profile_service.get_profile_record(row["profile_id"])
            self.assertEqual(record["environment_preset"], "auto")
            self.assertNotIn("environment_config", record)
            self.assertFalse(environment.product_environment_launch_arguments(record))

    def test_profile_without_environment_selection_defaults_to_auto(self):
        row = self.api.create_profile("Automatic")
        record = self.application.profile_service.get_profile_record(row["profile_id"])

        self.assertEqual(row["environment"]["preset"], "auto")
        self.assertEqual(row["environment"]["label"], "Auto")
        self.assertEqual(record["environment_preset"], "auto")
        self.assertNotIn("environment_config", record)
        self.assertEqual(environment.product_environment_launch_arguments(record), [])

    def test_auto_selected_when_creating_profile_keeps_default_runtime_behavior(self):
        row = self.api.create_profile(
            "Explicit Auto", environment_payload={"preset": "auto"}
        )
        record = self.application.profile_service.get_profile_record(row["profile_id"])

        self.assertEqual(row["environment"]["label"], "Auto")
        self.assertEqual(record["environment_preset"], "auto")
        self.assertNotIn("environment_config", record)
        self.assertEqual(environment.product_environment_launch_arguments(record), [])

    def test_renaming_auto_profile_preserves_auto(self):
        row = self.api.create_profile("Before")
        updated = self.api.update_profile(row["profile_id"], name="After")
        self.assertEqual(updated["name"], "After")
        self.assertEqual(updated["environment"]["preset"], "auto")
        record = self.application.profile_service.get_profile_record(row["profile_id"])
        self.assertEqual(record["environment_preset"], "auto")
        self.assertNotIn("environment_config", record)

    def test_legacy_generated_profile_is_presented_as_auto_without_catalog_migration(self):
        row = self.api.create_profile("Legacy generated", environment_payload={"preset": "generated"})
        stored_before = self.application.profile_service.get_profile_record(row["profile_id"])
        updated = self.api.update_profile(row["profile_id"], name="Renamed generated")
        stored_after = self.application.profile_service.get_profile_record(row["profile_id"])

        self.assertEqual(row["environment"]["label"], "Auto")
        self.assertEqual(updated["environment"]["label"], "Auto")
        self.assertEqual(stored_before["environment_preset"], "generated")
        self.assertEqual(stored_after["environment_preset"], "generated")
        self.assertEqual(stored_after["environment_config"], stored_before["environment_config"])

    def test_renaming_mobile_profile_preserves_mobile(self):
        row = self.api.create_profile("Before", environment_payload={"preset": "android_chromium"})
        updated = self.api.update_profile(row["profile_id"], name="After")
        self.assertEqual(updated["environment"]["preset"], "android_chromium")
        self.assertEqual(updated["environment"]["label"], "Mobile")

    def test_renaming_custom_profile_preserves_custom(self):
        row = self.api.create_profile("Before", environment_payload={
            "preset": "custom",
            "language": "vi-VN",
            "touch_mode": True,
        })
        updated = self.api.update_profile(row["profile_id"], name="After")
        self.assertEqual(updated["environment"]["preset"], "custom")
        self.assertEqual(updated["environment"]["label"], "Custom")
        self.assertEqual(updated["environment"]["language"], "vi-VN")

    def test_name_only_update_preserves_account_metadata(self):
        row = self.api.create_profile(
            "Before", account_input="fixture@example.com:fixture-password"
        )
        before = self.application.profile_service.get_profile_record(row["profile_id"])

        updated = self.api.update_profile(row["profile_id"], name="After")
        after = self.application.profile_service.get_profile_record(row["profile_id"])

        self.assertEqual(updated["account"], "fixture@example.com")
        self.assertEqual(after.get("account"), before.get("account"))
        self.assertEqual(after["environment_preset"], before["environment_preset"])
        self.assertEqual(after.get("environment_config"), before.get("environment_config"))

    def test_renaming_profile_preserves_proxy(self):
        row = self.api.create_profile("Before", proxy_payload={
            "enabled": True,
            "scheme": "http",
            "host": "127.0.0.1",
            "port": 8080,
        })
        updated = self.api.update_profile(row["profile_id"], name="After")
        self.assertEqual(updated["proxy"], {
            "enabled": True,
            "scheme": "http",
            "host": "127.0.0.1",
            "port": 8080,
        })

    def test_proxy_parse_is_transient_and_supports_authenticated_syntax(self):
        parsed = self.api.parse_proxy("http://user:fixture-pass@proxy.example:8080")
        self.assertTrue(parsed["authenticated"])
        self.assertEqual(parsed["host"], "proxy.example")
        row = self.api.create_profile("Proxy", proxy_payload=parsed)
        exported = json.loads(self.api.export_json([row["profile_id"]])["content"])[0]
        self.assertEqual(exported["proxy_username"], "user")
        self.assertEqual(exported["proxy_password"], "fixture-pass")

    def test_ui_preferences_are_application_owned_and_round_trip(self):
        saved = self.api.save_ui_preferences({
            "theme": "light",
            "density": "compact",
            "reduce_motion": True,
            "sidebar_collapsed": True,
            "visible_columns": ["status", "account", "status", "unknown"],
            "password": "must-not-persist",
        })
        self.assertEqual(saved["theme"], "light")
        self.assertEqual(saved["visible_columns"], ["account"])
        self.assertNotIn("density", saved)
        self.assertNotIn("sidebar_collapsed", saved)
        self.assertEqual(self.api.get_ui_preferences(), saved)
        raw = self.application.paths.ui_preferences_json.read_text(encoding="utf-8")
        self.assertNotIn("must-not-persist", raw)
        self.assertNotIn("password", raw)
        hidden = self.api.save_ui_preferences({"visible_columns": []})
        self.assertEqual(hidden["visible_columns"], [])
        self.assertEqual(self.api.get_ui_preferences()["visible_columns"], [])

    def test_legacy_system_theme_falls_back_to_dark_without_migrating_browser_data(self):
        path = self.application.paths.ui_preferences_json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"theme": "system", "visible_columns": []}), encoding="utf-8")
        self.assertEqual(self.api.get_ui_preferences()["theme"], "dark")
        self.assertEqual(self.api.save_ui_preferences({"theme": "system"})["theme"], "dark")

    def test_about_info_uses_repository_metadata_without_email_addresses(self):
        info = self.api.get_about_info()
        self.assertEqual(info["name"], "Trình quản lý đa tài khoản Discord")
        self.assertIn("Pre-final", info["status"])
        self.assertTrue(info["commit"])
        self.assertEqual(info["contributors"], ["merino sầu riêng"])
        self.assertIsNone(info["developer_profile_url"])
        self.assertIsNone(info["contributor_github_url"])

    def test_about_info_reads_optional_developer_profile_url_from_project_metadata(self):
        metadata_path = self.workspace.root / "revamped" / "resources" / "about.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps({"developer_profile_url": "https://example.invalid/merino"}),
            encoding="utf-8",
        )

        with patch(
            "revamped.core.ProjectPaths.project_root",
            new=property(lambda _paths: self.workspace.root),
        ):
            info = self.api.get_about_info()

        self.assertEqual(info["developer_profile_url"], "https://example.invalid/merino")
        self.assertEqual(info["contributor_github_url"], info["developer_profile_url"])

        metadata_path.write_text(
            json.dumps({"developer_profile_url": "javascript:alert(1)"}),
            encoding="utf-8",
        )
        with patch(
            "revamped.core.ProjectPaths.project_root",
            new=property(lambda _paths: self.workspace.root),
        ):
            self.assertIsNone(self.api.get_about_info()["developer_profile_url"])

    def test_batch_launch_is_ordered_and_reports_progress(self):
        first = self.api.create_profile("First")["profile_id"]
        second = self.api.create_profile("Second")["profile_id"]

        class FakeLauncher:
            def __init__(self):
                self.calls = []

            def launch_discord(self, profile_id):
                self.calls.append(profile_id)
                return True

        launcher = FakeLauncher()
        self.api.launcher = launcher
        job_id = self.api.launch_batch([first, second], delay=0.01)
        while True:
            state = self.api.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(launcher.calls, [first, second])
        self.assertEqual(state["result"]["completed"], 2)

    def test_batch_cancellation_stops_remaining_profiles(self):
        ids = [self.api.create_profile(name)["profile_id"] for name in ("One", "Two", "Three")]

        class FakeLauncher:
            def launch_discord(self, profile_id):
                return True

        self.api.launcher = FakeLauncher()
        job_id = self.api.launch_batch(ids, delay=0.2)
        time.sleep(0.04)
        self.api.cancel_batch(job_id)
        while True:
            state = self.api.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(state["status"], "cancelled")
        self.assertLess(state["result"]["completed"], len(ids))

    def test_batch_launch_reports_partial_failures_in_its_result(self):
        ids = [self.api.create_profile(name)["profile_id"] for name in ("One", "Two", "Three")]

        class PartiallyFailingLauncher:
            def launch_discord(self, profile_id):
                if profile_id == ids[1]:
                    raise RuntimeError("synthetic launch failure")
                return True

        self.api.launcher = PartiallyFailingLauncher()
        job_id = self.api.launch_batch(ids, delay=0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.api.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["result"]["requested"], 3)
        self.assertEqual(state["result"]["succeeded"], 2)
        self.assertEqual(state["result"]["failed"], 1)
        self.assertEqual(
            [item["status"] for item in state["result"]["results"]],
            ["launched", "error", "launched"],
        )

    def test_invalid_update_inputs_do_not_partially_rename_profile(self):
        profile = self.api.create_profile("Original")
        profile_id = profile["profile_id"]

        with self.assertRaises(InvalidAccountFormatError):
            self.api.update_profile(
                profile_id,
                name="Must not be saved",
                account_input="malformed account input",
            )
        self.assertEqual(self.api.get_profile(profile_id)["name"], "Original")
        self.assertFalse(self.api.get_profile(profile_id)["has_account"])

        with self.assertRaises(ProxyValidationError):
            self.api.update_profile(
                profile_id,
                name="Must still not be saved",
                proxy_payload={
                    "enabled": True,
                    "scheme": "http",
                    "host": "invalid host",
                    "port": 8080,
                },
            )
        self.assertEqual(self.api.get_profile(profile_id)["name"], "Original")


if __name__ == "__main__":
    unittest.main()
