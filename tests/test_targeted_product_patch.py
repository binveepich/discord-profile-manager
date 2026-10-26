"""Focused regression coverage for the targeted product-candidate patch."""

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from compatibility.fixtures import DisposableWorkspace
from revamped.main import compose_product_candidate
from revamped.product_api import ProductAPI
from revamped.product_main import PRODUCT_DISPLAY_NAME, PRODUCT_WINDOW_HEIGHT, PRODUCT_WINDOW_MIN_SIZE, PRODUCT_WINDOW_WIDTH


class DynamicInspector:
    def __init__(self):
        self.running = set()

    def using_directory(self, directory, exact=False):
        return str(Path(directory).resolve()) in self.running


class TargetedProductPatchTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("targeted-product-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.inspector = DynamicInspector()
        self.application = compose_product_candidate(
            self.workspace.root,
            process_inspector=self.inspector,
        )
        self.application.profile_service.initialize_metadata()
        self.api = ProductAPI(self.application)
        self.addCleanup(self.api.shutdown)

    def test_product_window_is_resizable_and_shell_supports_narrow_layouts(self):
        self.assertEqual((PRODUCT_WINDOW_WIDTH, PRODUCT_WINDOW_HEIGHT), (1600, 900))
        self.assertEqual(PRODUCT_WINDOW_MIN_SIZE, (1312, 738))
        self.assertEqual(PRODUCT_DISPLAY_NAME, "Trình quản lý đa tài khoản Discord")
        product_entrypoint = Path("revamped/product_main.py").read_text(encoding="utf-8")
        self.assertIn("resizable=True", product_entrypoint)
        self.assertIn("x=None", product_entrypoint)
        self.assertIn("fullscreen=False", product_entrypoint)
        source = Path("frontend/src/styles.css").read_text(encoding="utf-8")
        self.assertIn(".app-shell", source)
        self.assertIn("overflow: hidden", source)
        self.assertIn(".table-scroll", source)
        self.assertIn("max-width: 1199px", source)
        self.assertIn("minmax(0, 1fr) minmax(270px, 300px)", source)
        self.assertIn("quick-status-slot", source)
        self.assertIn("max-height: calc(100vh - 16px)", source)
        self.assertIn(".action-button:active", source)
        self.assertIn(".stats-card", source)
        self.assertIn("width: min(560px", source)
        header_source = Path("frontend/src/components/Header.jsx").read_text(encoding="utf-8")
        self.assertNotIn("aria-current=\"page\"", header_source)
        self.assertIn("DiscordIcon", header_source)
        self.assertIn("window_placement_builder=environment.product_window_placement_arguments", Path("revamped/main.py").read_text(encoding="utf-8"))

    def test_last_opened_newest_first_with_never_opened_at_bottom(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        self.application.profile_service.clock = lambda: now[0]
        first = self.api.create_profile("First")["profile_id"]
        second = self.api.create_profile("Second")["profile_id"]
        never = self.api.create_profile("Never")["profile_id"]
        self.application.profile_service.mark_profile_opened(first)
        now[0] = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.application.profile_service.mark_profile_opened(second)

        rows = self.api.list_profiles(sort="last_opened")
        self.assertEqual([row["profile_id"] for row in rows], [second, first, never])

    def test_status_poll_returns_only_status_and_tracks_process_exit(self):
        profile_id = self.api.create_profile("Running state")["profile_id"]
        profile_dir = str(self.application.profile_service.get_profile_dir(profile_id).resolve())
        self.inspector.running.add(profile_dir)
        self.assertEqual(self.api.refresh_status(), [{"profile_id": profile_id, "status": "Running"}])
        self.inspector.running.clear()
        self.assertEqual(self.api.refresh_status(), [{"profile_id": profile_id, "status": "Closed"}])

    def test_structured_account_input_stages_and_exports_owned_credentials(self):
        secret = "structured-password"
        totp = "structured-totp"
        row = self.api.create_profile(account_input={
            "email": "structured@example.com",
            "password": secret,
            "totp_secret": totp,
        })
        self.assertEqual(row["account"], "structured@example.com")
        exported = self.api.export_json()["content"] + self.api.export_csv()["content"]
        self.assertIn(secret, exported)
        self.assertIn(totp.upper(), exported)
        self.assertIn(secret, (
            self.application.extension_service.profile_extension_path(row["profile_id"])
            / "config.js"
        ).read_text(encoding="utf-8"))

    def test_exposed_sort_options_remove_account(self):
        header = Path("frontend/src/components/Header.jsx").read_text(encoding="utf-8")
        self.assertNotIn('value="account"', header)
        self.assertIn('["id", "Mã hồ sơ"]', header)
        self.assertNotIn("<select", header)
        self.assertIn('role="listbox"', header)
        self.assertIn('event.key === "Escape"', header)

    def test_autofill_required_extension_is_staged_loaded_and_pinned(self):
        state = self.application.extension_service.get_registry_state()
        self.assertEqual(
            [item["name"] for item in state["built_ins"]],
            ["discord-autofill-extension"],
        )
        row = self.api.create_profile("Extensions")
        staged = self.application.extension_service.get_profile_extension_paths(row["profile_id"])
        self.assertEqual(
            {path.name for path in staged},
            {"discord-autofill-extension"},
        )
        registration = self.application.extension_service.get_profile_extension_registration(row["profile_id"])
        self.assertEqual(len(registration["pinned_actions"]), 1)
        self.assertFalse(state["quarantined"])


if __name__ == "__main__":
    unittest.main()
