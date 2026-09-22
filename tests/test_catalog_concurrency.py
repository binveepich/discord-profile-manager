"""Regression tests for profiles.json read/write coordination."""

from concurrent.futures import ThreadPoolExecutor
import json
import time
import unittest
from unittest.mock import Mock, patch

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ProfileManagerError
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.storage import ProfileCatalogStore


class CatalogConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("catalog-concurrency-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.application = compose_product_candidate(self.workspace.root)
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)
        # Extension copying is covered by the product extension tests.  These
        # storage tests keep the real catalog/profile transaction but replace
        # that unrelated per-profile I/O with a disposable no-op.
        self.extension_setup = patch.object(
            self.api.extension_service,
            "ensure_required_extensions",
            return_value=None,
        )
        self.extension_setup.start()
        self.addCleanup(self.extension_setup.stop)

    def wait_for_job(self, job_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.api.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                return state
            time.sleep(0.01)
        self.fail(f"job did not reach a terminal state: {job_id}")

    @staticmethod
    def import_text(count):
        return "\n".join(
            f"synthetic{index:03d}@example.invalid:fixture-password-{index:03d}"
            for index in range(1, count + 1)
        )

    def fast_profile_create(self, display_name, account_input=None, **_kwargs):
        """Keep transaction tests focused on catalog publication."""
        return self.application.profile_service.create_profile(display_name)

    def test_load_catalog_and_refresh_status_are_read_only(self):
        profile_id = self.api.create_profile("Read only")["profile_id"]
        service = self.application.profile_service
        service._save_catalog = Mock(wraps=service._save_catalog)

        # A physical orphan must not make a read perform migration work.
        orphan = self.application.paths.profiles_dir / "profile_0099" / "Default"
        orphan.mkdir(parents=True)
        (orphan / "Preferences").write_text("{}", encoding="utf-8")
        before = self.application.paths.profiles_json.read_bytes()

        self.assertNotIn("profile_0099", {item["profile_id"] for item in service.get_profile_metadata()})
        self.assertEqual(self.api.refresh_status([profile_id]), [
            {"profile_id": profile_id, "status": "Closed"}
        ])
        self.assertEqual(service._save_catalog.call_count, 0)
        self.assertEqual(self.application.paths.profiles_json.read_bytes(), before)

    def test_concurrent_create_and_status_polling_do_not_corrupt_catalog(self):
        errors = []

        def poll():
            for _ in range(50):
                try:
                    self.api.refresh_status()
                    json.loads(self.application.paths.profiles_json.read_text(encoding="utf-8"))
                except Exception as error:  # pragma: no cover - assertion below reports it
                    errors.append(error)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(poll) for _ in range(4)]
            creator = executor.submit(self.api.create_profile, "Concurrent")
            creator.result(timeout=30)
            for future in futures:
                future.result(timeout=30)

        self.assertEqual(errors, [])
        catalog = json.loads(self.application.paths.profiles_json.read_text(encoding="utf-8"))
        self.assertEqual(len(catalog["profiles"]), 1)

    def test_repeated_status_polling_does_not_write_or_flood_storage_errors(self):
        service = self.application.profile_service
        service._save_catalog = Mock(wraps=service._save_catalog)
        expected = []
        for _ in range(20):
            expected = self.api.refresh_status()
        self.assertEqual(expected, [])
        self.assertEqual(service._save_catalog.call_count, 0)
        json.loads(self.application.paths.profiles_json.read_text(encoding="utf-8"))

    def test_96_record_import_has_one_final_catalog_commit_and_terminal_completion(self):
        replacements = 0
        original = ProfileCatalogStore._replace_with_bounded_retry

        def count_replacement(source, destination, **kwargs):
            nonlocal replacements
            replacements += 1
            return original(source, destination, **kwargs)

        with patch.object(
            ProfileCatalogStore,
            "_replace_with_bounded_retry",
            side_effect=count_replacement,
        ), patch.object(
            self.api,
            "_create_profile_internal",
            side_effect=self.fast_profile_create,
        ):
            job_id = self.api.import_accounts_txt(self.import_text(96))
            state = self.wait_for_job(job_id, timeout=60)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["result"]["created"], 96)
        self.assertEqual(replacements, 1)
        self.assertEqual(len(json.loads(
            self.application.paths.profiles_json.read_text(encoding="utf-8")
        )["profiles"]), 96)

    def test_status_polling_during_import_keeps_catalog_valid(self):
        with patch.object(
            self.api,
            "_create_profile_internal",
            side_effect=self.fast_profile_create,
        ):
            job_id = self.api.import_accounts_txt(self.import_text(24))
            observed = 0
            while True:
                self.api.refresh_status()
                json.loads(self.application.paths.profiles_json.read_text(encoding="utf-8"))
                observed += 1
                state = self.api.get_job(job_id)
                if state["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
        self.assertGreater(observed, 0)
        self.assertEqual(state["status"], "completed")

    def test_failed_final_catalog_commit_is_terminal_and_preserves_previous_catalog(self):
        original = self.application.paths.profiles_json.read_bytes()
        failure = ProfileManagerError("synthetic catalog write failure")
        with patch.object(self.application.profile_service.catalog_store, "save", side_effect=failure), \
             patch.object(self.api, "_create_profile_internal", side_effect=self.fast_profile_create):
            job_id = self.api.import_accounts_txt(self.import_text(3))
            state = self.wait_for_job(job_id)

        self.assertEqual(state["status"], "failed")
        self.assertIn("synthetic catalog write failure", state["error"])
        self.assertEqual(self.application.paths.profiles_json.read_bytes(), original)
        self.assertEqual(self.api.refresh_status(), [])

    def test_existing_profile_id_and_directory_survive_import(self):
        existing = self.api.create_profile("Existing")
        existing_dir = self.application.profile_service.get_profile_dir(existing["profile_id"])
        with patch.object(
            self.api,
            "_create_profile_internal",
            side_effect=self.fast_profile_create,
        ):
            result = self.api.import_accounts_txt_sync(self.import_text(2))

        self.assertEqual(result["created"], 2)
        self.assertTrue(existing_dir.is_dir())
        self.assertEqual(
            self.application.profile_service.get_profile_dir(existing["profile_id"]),
            existing_dir,
        )
        ids = [item["profile_id"] for item in self.api.list_profiles()]
        self.assertEqual(ids[0], existing["profile_id"])
        self.assertEqual(len(set(ids)), 3)


if __name__ == "__main__":
    unittest.main()
