"""Tests for scripts/import_legacy_profiles.py using synthetic legacy installs only."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from revamped.main import compose_product_candidate
from revamped.storage import ProfileCatalogStore
from revamped.core import ProfileManagerError


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_legacy_profiles.py"
_spec = importlib.util.spec_from_file_location("import_legacy_profiles", SCRIPT)
importer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = importer  # dataclasses resolve the module through sys.modules
_spec.loader.exec_module(importer)

SECRET = "synthetic-secret-pass-7731"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


def config_js(email):
    return (
        "// Discord Auto-fill Extension Configuration\n"
        "    const ACCOUNT = {\n"
        f'        email: "{email}",\n'
        f'        password: "{SECRET}",\n'
        f'        totpSecret: "{TOTP_SECRET}"\n'
        "    };\n"
    )


def make_install(base, label, entries):
    """Build a synthetic portable install: <base>/<label>/ungoogled-chromium-portable/data."""
    install = Path(base) / label / "ungoogled-chromium-portable"
    data = install / "data"
    info = {}
    for legacy_id, options in entries:
        folder = data / legacy_id
        folder.mkdir(parents=True)
        if options.get("registered", True):
            info[legacy_id] = {"name": options.get("name", legacy_id), "avatar_icon": "x", "created": 1789000000}
        (folder / "Preferences").write_text("{}", encoding="utf-8")
        if options.get("email"):
            extension = folder / "Unpacked Extensions" / "discord-autofill-extension"
            extension.mkdir(parents=True)
            (extension / "config.js").write_text(config_js(options["email"]), encoding="utf-8")
        cache = folder / "Default" / "Cache" / "Cache_Data"
        cache.mkdir(parents=True)
        (cache / "data_0").write_bytes(b"c" * 2048)
        storage = folder / "Default" / "Local Storage" / "leveldb"
        storage.mkdir(parents=True)
        (storage / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
        if options.get("flat_marker"):
            (folder / "Cookies").write_bytes(b"x")
        if options.get("missing_last_used"):
            (folder / "Local State").write_text(
                json.dumps({"profile": {"last_used": "Profile 99"}}), encoding="utf-8"
            )
    (data / "Local State").write_text(json.dumps({"profile": {"info_cache": info}}), encoding="utf-8")
    return install


def make_state_root(base):
    root = Path(base) / "state"
    root.mkdir()
    compose_product_candidate(root).profile_service.initialize_metadata()
    return root


def run_importer(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = importer.main(list(args))
    return code, output.getvalue()


class ImportLegacyProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = make_state_root(base)
        self.ffa = make_install(base, "FFA Discord", [
            ("Profile 1", {"name": "One", "email": "a@example.invalid"}),
            ("Profile 2", {"name": "Two", "email": "b@example.invalid"}),
            ("Profile 3", {"name": "Flat", "email": "f@example.invalid", "flat_marker": True}),
            ("Profile 4", {"name": "NoLastUsed", "email": "g@example.invalid", "missing_last_used": True}),
            ("Profile 5", {"name": "Orphan", "email": "o@example.invalid", "registered": False}),
        ])
        self.old = make_install(base, "OLD FFA Discord", [
            ("Profile 1", {"name": "Duplicate", "email": "a@example.invalid"}),
            ("Profile 2", {"name": "New", "email": "c@example.invalid"}),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, *extra):
        sources = []
        for install in (self.ffa, self.old):
            sources.extend(["--source", str(install)])
        return ["--root", str(self.root), *sources, *extra]

    def catalog_bytes(self):
        return (self.root / "config" / "profiles.json").read_bytes()

    def catalog(self):
        return json.loads(self.catalog_bytes().decode("utf-8"))["profiles"]

    def report_files(self):
        return sorted((self.root / "logs" / "legacy-import").glob("*/report.json"))

    def test_dry_run_writes_nothing(self):
        before = self.catalog_bytes()
        code, output = run_importer(*self.args())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.catalog_bytes(), before)
        self.assertFalse((self.root / "logs").exists())
        self.assertFalse(any((self.root / "profiles").glob("profile_*")))
        self.assertIn("DRY RUN", output)

    def test_apply_imports_eligible_profiles_and_reports_skips(self):
        code, output = run_importer(*self.args("--apply"))
        self.assertEqual(code, 0, output)
        catalog = self.catalog()
        self.assertEqual(sorted(p["profile_id"] for p in catalog), ["profile_0001", "profile_0002", "profile_0003"])
        self.assertEqual(
            sorted(p["account"]["email"] for p in catalog),
            ["a@example.invalid", "b@example.invalid", "c@example.invalid"],
        )
        report = json.loads(self.report_files()[-1].read_text(encoding="utf-8"))
        reasons = " | ".join(item["reason"] for item in report["skipped"])
        self.assertIn("last_used", reasons)
        self.assertIn("shared-root layout", reasons)
        self.assertIn("orphan folder", reasons)
        self.assertIn("same account", reasons)
        self.assertTrue(report["apply"]["published"])

    def test_listing_and_browser_layout_resolve_for_imported_profiles(self):
        run_importer(*self.args("--apply"))
        composition = compose_product_candidate(self.root)
        service = composition.profile_service
        self.assertEqual(len(service.get_profile_metadata()), 3)
        for profile_id in ("profile_0001", "profile_0002", "profile_0003"):
            service.get_browser_profile_dir(profile_id)

    def test_secrets_never_reach_output_or_report(self):
        code, output = run_importer(*self.args("--apply"))
        self.assertEqual(code, 0, output)
        report_text = self.report_files()[-1].read_text(encoding="utf-8")
        for text in (output, report_text):
            self.assertNotIn(SECRET, text)
            self.assertNotIn(TOTP_SECRET, text)
        self.assertNotIn(SECRET, self.catalog_bytes().decode("utf-8"))
        self.assertNotIn(TOTP_SECRET, self.catalog_bytes().decode("utf-8"))

    def test_rerun_is_idempotent(self):
        run_importer(*self.args("--apply"))
        before = self.catalog_bytes()
        code, output = run_importer(*self.args("--apply"))
        self.assertEqual(code, 0, output)
        self.assertIn("Created: 0", output)
        self.assertEqual(self.catalog_bytes(), before)

    def test_failed_publish_registers_nothing_and_moves_copies_aside(self):
        before = self.catalog_bytes()
        with mock.patch.object(ProfileCatalogStore, "save", side_effect=ProfileManagerError("synthetic publish failure")):
            code, output = run_importer(*self.args("--apply"))
        self.assertEqual(code, 3)
        self.assertIn("Published: False", output)
        self.assertEqual(self.catalog_bytes(), before)
        self.assertFalse(list((self.root / "profiles").glob("profile_*")))
        self.assertEqual(len(list((self.root / "profiles").glob(".import-partial-profile_*"))), 3)

    def test_one_failed_copy_is_moved_aside_and_the_rest_import(self):
        real_copytree = importer.shutil.copytree
        calls = {"count": 0}

        def flaky_copytree(source, destination, *args, **kwargs):
            # shutil.copytree recurses through the public name; count only the profile-level copies.
            if Path(destination).parent.name != "profiles":
                return real_copytree(source, destination, *args, **kwargs)
            calls["count"] += 1
            if calls["count"] == 2:
                Path(destination).mkdir(parents=True)
                (Path(destination) / "partial.bin").write_bytes(b"half")
                raise OSError("synthetic copy failure")
            return real_copytree(source, destination, *args, **kwargs)

        with mock.patch.object(importer.shutil, "copytree", side_effect=flaky_copytree):
            code, output = run_importer(*self.args("--apply"))
        self.assertEqual(code, 3)
        catalog = self.catalog()
        self.assertEqual(sorted(p["profile_id"] for p in catalog), ["profile_0001", "profile_0002"])
        self.assertEqual(
            sorted(p["account"]["email"] for p in catalog),
            ["a@example.invalid", "c@example.invalid"],
        )
        self.assertTrue(list((self.root / "profiles").glob(".import-partial-profile_0002-*")))

    def test_skip_caches_keeps_storage_and_drops_caches(self):
        code, output = run_importer(*self.args("--apply", "--skip-caches"))
        self.assertEqual(code, 0, output)
        destination = self.root / "profiles" / "profile_0001" / "Default"
        self.assertFalse((destination / "Cache").exists())
        self.assertTrue((destination / "Local Storage" / "leveldb" / "CURRENT").is_file())


if __name__ == "__main__":
    unittest.main()
