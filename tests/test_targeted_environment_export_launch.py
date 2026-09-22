"""Regression coverage for the product-candidate patch boundaries."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from revamped import environment
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.processes import ChromiumProcessInspector


class PendingProcess:
    def poll(self):
        return None


class TargetedEnvironmentExportLaunchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dpm-targeted-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.launch_calls = []

        def process_factory(command, **_kwargs):
            self.launch_calls.append(command)
            return PendingProcess()

        self.application = compose_product_candidate(
            self.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
            process_factory=process_factory,
        )
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)

    def test_new_profiles_persist_distinct_environment_without_device_scale(self):
        first = self.api.create_profile("First")
        second = self.api.create_profile("Second")
        self.assertNotEqual(
            first["environment"]["environment_signature"],
            second["environment"]["environment_signature"],
        )
        for row in (first, second):
            record = self.application.profile_service.get_profile_record(row["profile_id"])
            self.assertEqual(
                record["environment_config"]["environment_schema"],
                environment.PRODUCT_ENVIRONMENT_SCHEMA,
            )
            self.assertNotIn("device_scale_factor", record["environment_config"])
            command = self.application.launcher.build_command(
                row["profile_id"],
                self.application.profile_service.get_profile_dir(row["profile_id"]),
                record,
            )
            self.assertFalse(any("force-device-scale" in item for item in command))

    def test_mobile_identity_keeps_desktop_usable_physical_bounds(self):
        self.api.create_profile("Mobile")
        row = self.api.generate_environment("profile_0001", "Mobile")
        geometry = row["environment"]["window_geometry"]
        self.assertGreaterEqual(geometry["width"], environment.PRODUCT_WINDOW_MIN_WIDTH)
        self.assertGreaterEqual(geometry["height"], environment.PRODUCT_WINDOW_MIN_HEIGHT)
        self.assertNotEqual((geometry["width"], geometry["height"]), (390, 844))

    def test_full_exports_use_one_schema_and_selected_profiles(self):
        row = self.api.create_profile(
            "Export me",
            account_input="export@example.com:export-password:export-totp",
            proxy_payload="http://proxy-user:proxy-password@proxy.example:8080",
        )
        selected = [row["profile_id"]]
        json_data = json.loads(self.api.export_json(selected)["content"])
        csv_data = self.api.export_csv(selected)["content"]
        txt_data = self.api.export_txt(selected)["content"]
        self.assertEqual(list(json_data[0]), list(self.api.export_json(selected)["columns"]))
        self.assertIn("export-password", json_data[0]["password"])
        self.assertEqual(json_data[0]["proxy_username"], "proxy-user")
        self.assertIn("export-password", csv_data)
        self.assertIn("proxy-password", txt_data)

    def test_non_launch_operations_never_call_process_factory(self):
        self.api.create_profile("Create")
        self.api.update_profile("profile_0001", "Updated", environment_payload={"preset": "Desktop"})
        self.api.generate_environment("profile_0001", "Desktop")
        self.api.import_accounts_txt_sync("imported@example.com:import-password")
        self.api.get_runtime_info()
        self.assertEqual(self.launch_calls, [])

    def test_only_explicit_launch_api_calls_process_factory(self):
        browser = self.root / "browser" / "chrome.exe"
        browser.parent.mkdir(parents=True, exist_ok=True)
        browser.write_bytes(b"synthetic runtime")
        row = self.api.create_profile("Launch")
        self.api.launch_profile(row["profile_id"])
        self.assertEqual(len(self.launch_calls), 1)


if __name__ == "__main__":
    unittest.main()
