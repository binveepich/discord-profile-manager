"""Focused tests for the React/pywebview product contract."""

import json
from pathlib import Path
import time
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.accounts import derive_profile_name, parse_account_string
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

    def test_txt_import_generates_environment_and_reports_bad_lines(self):
        result = self.api.import_accounts_txt_sync(
            "one@example.com:fixture-one\nnot-an-account\ntwo@example.com:fixture-two:totp"
        )
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["errors"][0]["line"], 2)
        rows = self.api.list_profiles()
        self.assertEqual({row["environment"]["preset"] for row in rows}, {"generated"})

    def test_proxy_parse_is_transient_and_supports_authenticated_syntax(self):
        parsed = self.api.parse_proxy("http://user:fixture-pass@proxy.example:8080")
        self.assertTrue(parsed["authenticated"])
        self.assertEqual(parsed["host"], "proxy.example")
        row = self.api.create_profile("Proxy", proxy_payload=parsed)
        exported = json.loads(self.api.export_json([row["profile_id"]])["content"])[0]
        self.assertEqual(exported["proxy_username"], "user")
        self.assertEqual(exported["proxy_password"], "fixture-pass")

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


if __name__ == "__main__":
    unittest.main()
