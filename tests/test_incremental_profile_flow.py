"""Regression coverage for product profile deltas and lightweight refreshes."""

from pathlib import Path
from unittest.mock import patch
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.processes import ChromiumProcessInspector


class IncrementalProfileFlowTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("incremental-flow-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.application = compose_product_candidate(
            self.workspace.root,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)

    def fast_profile_create(self, display_name, account_input=None, **_kwargs):
        return self.application.profile_service.create_profile(display_name)

    def test_create_edit_and_delete_use_deltas_without_full_list(self):
        with patch.object(self.api, "list_profiles", wraps=self.api.list_profiles) as full_list:
            created = self.api.create_profile("Created")
            self.assertEqual(created["profile_id"], "profile_0001")
            self.assertEqual(created["name"], "Created")

            updated = self.api.update_profile(created["profile_id"], name="Renamed")
            self.assertEqual(updated["name"], "Renamed")

            deleted = self.api.delete_profiles(
                [created["profile_id"]], confirmed=True
            )
            self.assertEqual(deleted["deleted_profile_ids"], [created["profile_id"]])
            self.assertEqual(full_list.call_count, 0)

    def test_batch_delete_returns_only_successful_ids_without_full_list(self):
        ids = [self.api.create_profile(name)["profile_id"] for name in ("One", "Two", "Three")]
        with patch.object(self.api, "list_profiles", wraps=self.api.list_profiles) as full_list:
            result = self.api.delete_profiles(ids, confirmed=True)
        self.assertEqual(result["deleted_profile_ids"], ids)
        self.assertEqual(full_list.call_count, 0)

    def test_import_terminal_result_is_a_successful_profile_delta(self):
        text = "\n".join(
            [
                "one@example.invalid:fixture-one",
                "not-an-account",
                "two@example.invalid:fixture-two:totp",
            ]
        )
        with patch.object(self.api, "_create_profile_internal", side_effect=self.fast_profile_create), \
             patch.object(self.api, "list_profiles", wraps=self.api.list_profiles) as full_list:
            result = self.api.import_accounts_txt_sync(text)

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(len(result["profiles"]), 2)
        self.assertEqual(
            {row["name"] for row in result["profiles"]},
            {"one", "two"},
        )
        self.assertEqual(full_list.call_count, 0)

        # The explicit authoritative path still reconstructs the same state.
        rows = self.api.list_profiles()
        self.assertEqual({row["profile_id"] for row in rows}, {
            row["profile_id"] for row in result["profiles"]
        })

    def test_96_record_import_has_delta_and_no_full_list(self):
        text = "\n".join(
            f"fixture{index:03d}@example.invalid:fixture-password-{index:03d}"
            for index in range(1, 97)
        )
        with patch.object(self.api, "_create_profile_internal", side_effect=self.fast_profile_create), \
             patch.object(self.api, "list_profiles", wraps=self.api.list_profiles) as full_list:
            result = self.api.import_accounts_txt_sync(text)

        self.assertEqual(result["created"], 96)
        self.assertEqual(len(result["profiles"]), 96)
        self.assertEqual(full_list.call_count, 0)

    def test_status_refresh_is_delta_and_uses_one_bulk_process_walk(self):
        profile_id = self.api.create_profile("Status")["profile_id"]
        inspector = self.application.process_inspector
        with patch.object(self.api, "list_profiles", wraps=self.api.list_profiles) as full_list, \
             patch.object(inspector, "using_directories", wraps=inspector.using_directories) as bulk:
            updates = self.api.refresh_status()
        self.assertEqual(updates, [{"profile_id": profile_id, "status": "Closed"}])
        self.assertEqual(full_list.call_count, 0)
        self.assertEqual(bulk.call_count, 1)

    def test_frontend_keeps_full_refresh_for_startup_manual_refresh_only(self):
        app_source = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
        import_source = Path("frontend/src/dialogs/BatchImportDialog.jsx").read_text(encoding="utf-8")
        self.assertEqual(app_source.count("loadProfiles();"), 1)
        self.assertIn("onSaved={handleProfileSaved}", app_source)
        self.assertIn("onDone={handleImportDone}", app_source)
        self.assertIn("onDone(result);", import_source)
        self.assertEqual(import_source.count("onDone(result);"), 1)
        self.assertNotIn("window.location.reload", app_source)


if __name__ == "__main__":
    unittest.main()
