"""R14 product/development boundary, extension quarantine, and rollback checks."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT
from revamped.accounts import ACCOUNT_MODE_PRODUCT
from revamped.core import (
    ExtensionError,
    ExtensionDeploymentError,
    InvalidAccountFormatError,
    ProfileManagerError,
    PRODUCT_WORKSPACE_MARKER,
    WORKSPACE_DEVELOPMENT,
    WORKSPACE_PRODUCT,
)
from revamped.extensions import (
    PROHIBITED_EXTENSION_NAMES,
    REQUIRED_EXTENSION_NAMES,
)
from revamped.main import compose, compose_product
from revamped.processes import ChromiumProcessInspector
from scripts import check_refactor_integrity as integrity
from scripts.verify_revamped import _protected_runtime_snapshot


class PendingProcess:
    def poll(self):
        return None


class R14ProductBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r14-boundary-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.inspector = ChromiumProcessInspector(process_iter=lambda *_: [])

    def test_development_and_product_roots_require_distinct_explicit_decisions(self):
        development = compose(self.workspace.root, process_inspector=self.inspector)
        self.assertEqual(development.workspace_kind, WORKSPACE_DEVELOPMENT)
        self.assertFalse((self.workspace.root / PRODUCT_WORKSPACE_MARKER).exists())

        with self.assertRaisesRegex(ProfileManagerError, "requires --product-root"):
            compose(
                self.workspace.root,
                account_mode=ACCOUNT_MODE_PRODUCT,
                process_inspector=self.inspector,
            )

        product = compose_product(self.workspace.root / "product", process_inspector=self.inspector)
        self.assertEqual(product.workspace_kind, WORKSPACE_PRODUCT)
        self.assertEqual(product.account_mode, ACCOUNT_MODE_PRODUCT)
        self.assertTrue((product.paths.root / PRODUCT_WORKSPACE_MARKER).is_file())
        self.assertNotEqual(product.paths.profiles_json, development.paths.profiles_json)

    def test_composed_development_mode_refuses_credential_fields_but_accepts_synthetic_identity(self):
        application = compose(self.workspace.root, process_inspector=self.inspector)
        profile_id = application.profile_service.create_profile("Synthetic identity")
        with self.assertRaisesRegex(InvalidAccountFormatError, "refuses passwords"):
            application.account_service.set_account(
                profile_id, "synthetic@example.invalid:password"
            )
        account = application.account_service.set_account(
            profile_id, "synthetic@example.invalid"
        )
        self.assertEqual(
            account,
            {"mode": "development", "email": "synthetic@example.invalid"},
        )
        catalog = application.paths.profiles_json.read_text(encoding="utf-8")
        self.assertNotIn("password", catalog.casefold())

    def test_product_root_refuses_repository_live_roots_and_unmarked_existing_state(self):
        for unsafe in (
            PROJECT_ROOT,
            PROJECT_ROOT / "profiles",
            PROJECT_ROOT / "profiles" / "new-product-root",
            PROJECT_ROOT / "config",
            PROJECT_ROOT / "config" / "new-product-root",
        ):
            with self.subTest(root=unsafe), self.assertRaises(ProfileManagerError):
                compose_product(unsafe, process_inspector=self.inspector)

        existing = self.workspace.root / "unmarked"
        (existing / "profiles").mkdir(parents=True)
        (existing / "profiles" / "legacy-profile-marker").write_text(
            "must remain", encoding="utf-8"
        )
        with self.assertRaisesRegex(ProfileManagerError, "not product-owned"):
            compose_product(existing, process_inspector=self.inspector)
        self.assertFalse((existing / PRODUCT_WORKSPACE_MARKER).exists())
        self.assertTrue((existing / "profiles" / "legacy-profile-marker").is_file())

    def test_product_account_accepts_only_safe_metadata_and_never_stages_token_extension(self):
        application = compose_product(self.workspace.root / "product", process_inspector=self.inspector)
        profile_id = application.profile_service.create_profile("Product")
        account = application.account_service.set_product_account(
            profile_id, "person@example.com", "Primary"
        )
        self.assertEqual(account["mode"], ACCOUNT_MODE_PRODUCT)

        secret = "r14-never-store-this"
        with self.assertRaisesRegex(InvalidAccountFormatError, "password|token|TOTP"):
            application.account_service.set_product_account(
                profile_id, "person@example.com", "Primary", password=secret
            )
        catalog_text = application.paths.profiles_json.read_text(encoding="utf-8")
        self.assertNotIn(secret, catalog_text)
        self.assertNotIn(
            "discord-token-extractor-extension",
            application.extension_service.get_global_policy()["enabled_extensions"],
        )
        state = application.extension_service.get_registry_state()
        self.assertEqual(
            [item["name"] for item in state["built_ins"]],
            list(REQUIRED_EXTENSION_NAMES),
        )
        self.assertEqual(state["quarantined"], [])

    def test_product_launch_loads_required_token_extension_even_from_stale_policy(self):
        commands = []

        def record(command, **_kwargs):
            commands.append(command)
            return PendingProcess()

        application = compose_product(
            self.workspace.root / "product",
            process_inspector=self.inspector,
            process_factory=record,
        )
        application.launcher.launcher_path = self.workspace.root / "chrome.exe"
        application.launcher.launcher_path.write_bytes(b"synthetic runtime")
        profile_id = application.profile_service.create_profile("Product launch")
        application.paths.extension_policy_json.parent.mkdir(parents=True, exist_ok=True)
        application.paths.extension_policy_json.write_text(
            json.dumps({
                "version": 1,
                "enabled_extensions": ["discord-token-extractor-extension"],
            }),
            encoding="utf-8",
        )

        application.extension_service.enable_extension(
            "discord-token-extractor-extension"
        )
        application.extension_service.ensure_profile_extension(
            profile_id, "discord-token-extractor-extension"
        )
        self.assertTrue(application.launcher.launch_discord(profile_id))
        load = next(item for item in commands[-1] if item.startswith("--load-extension="))
        self.assertEqual(
            {Path(item).name for item in load.split("=", 1)[1].split(",")},
            {*REQUIRED_EXTENSION_NAMES, "discord-token-extractor-extension"},
        )
        self.assertTrue(
            (
                application.profile_service.get_profile_dir(profile_id)
                / "Unpacked Extensions"
                / "discord-token-extractor-extension"
            ).exists()
        )

    def test_product_account_update_rolls_back_local_config_when_metadata_publish_fails(self):
        application = compose_product(self.workspace.root / "product", process_inspector=self.inspector)
        profile_id = application.profile_service.create_profile("Rollback")
        config = application.extension_service.profile_extension_path(profile_id) / "config.js"
        config.parent.mkdir(parents=True, exist_ok=True)
        original = b"const ACCOUNT = {email: 'synthetic@example.invalid', password: 'old'};\n"
        config.write_bytes(original)

        with patch.object(
            application.account_service,
            "_set_account_metadata",
            side_effect=ProfileManagerError("synthetic metadata failure"),
        ):
            with self.assertRaises(ProfileManagerError):
                application.account_service.set_product_account(
                    profile_id, "person@example.com", "Primary"
                )

        self.assertEqual(config.read_bytes(), original)
        self.assertIsNone(application.account_service.get_account(profile_id))
        self.assertEqual(
            list(config.parent.glob(".account-config-*.bak")), []
        )

    def test_product_account_update_keeps_old_association_when_new_publish_fails(self):
        application = compose_product(self.workspace.root / "product", process_inspector=self.inspector)
        profile_id = application.profile_service.create_profile("Association rollback")
        old = application.account_service.set_product_account(
            profile_id, "old@example.com", "Old"
        )
        with patch.object(
            application.account_service,
            "_set_account_metadata",
            side_effect=ProfileManagerError("synthetic metadata failure"),
        ):
            with self.assertRaises(ProfileManagerError):
                application.account_service.set_product_account(
                    profile_id, "new@example.com", "New"
                )
        self.assertEqual(application.account_service.get_account(profile_id), old)

    def test_integrity_classifies_baseline_changes_without_relabeling_them(self):
        expected = "immutable-baseline"
        self.assertIn(
            "UNAPPROVED MODIFICATION",
            integrity.classify_protected_file("main.py", expected, "different"),
        )
        self.assertIn(
            "DELETED OR UNREADABLE",
            integrity.classify_protected_file("main.py", expected, exists=False),
        )
        self.assertIn(
            "RENAMED/MOVED",
            integrity.classify_protected_file(
                "main.py", expected, exists=False, moved_to="moved-main.py"
            ),
        )
        self.assertIn(
            "APPROVED R14",
            integrity.classify_protected_file(
                "main.py", expected, "different", approved="R14 remediation"
            ),
        )
        self.assertIn(
            integrity.git_blob_hash(PROJECT_ROOT / "main.py"),
            {
                integrity.IMMUTABLE_BASELINE["main.py"],
                integrity.APPROVED_MILESTONE_HASHES["Beta step 8 product entrypoint"]["main.py"],
            },
        )

    def test_integrity_rejects_unexpected_protected_untracked_paths(self):
        with patch.object(
            integrity,
            "_untracked_paths",
            return_value={"profiles/unexpected-r14-fixture"},
        ):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(integrity.check())

    def test_ignored_runtime_snapshot_detects_disposable_root_mutation_without_reading_live_data(self):
        root = self.workspace.root / "runtime-boundary"
        profile = root / "profiles" / "profile_0001"
        profile.mkdir(parents=True)
        marker = profile / "state"
        marker.write_text("one", encoding="utf-8")
        before = _protected_runtime_snapshot(root)
        marker.write_text("two", encoding="utf-8")
        after = _protected_runtime_snapshot(root)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
