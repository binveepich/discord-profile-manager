"""Startup contract for the loading splash.

The splash calls the catalog write as a bridge task, so the window opens first. A malformed catalog must surface as a
ProfileManagerError for the critical splash tasks, and non-critical warnings must be logged as one short line.
"""

import contextlib
import io
import types
import unittest
from unittest.mock import patch

from compatibility.fixtures import DisposableWorkspace
from revamped import product_main
from revamped.core import ProfileManagerError
from revamped.main import compose_product_candidate
from revamped.processes import ChromiumProcessInspector
from revamped.product_api import ProductAPI
from revamped.profiles import ProfileService


LOGGER_NAME = "discord-profile-manager.product"


def _inspector():
    return ChromiumProcessInspector(process_iter=lambda *_: [])


class _Hook:
    """Accepts `window.events.closing += handler` as pywebview does."""

    def __iadd__(self, handler):
        return self


class _WindowEvents:
    def __init__(self):
        self.closing = _Hook()
        self.shown = types.SimpleNamespace(wait=lambda *_: False)


class ProductStartupApiTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("startup-api-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.composition = compose_product_candidate(self.workspace.root, process_inspector=_inspector())
        self.api = ProductAPI(self.composition)
        self.addCleanup(self.api.shutdown)

    def test_initialize_catalog_publishes_the_catalog_and_reports_its_size(self):
        catalog_path = self.workspace.root / "config" / "profiles.json"
        self.assertFalse(catalog_path.exists())

        self.assertEqual(self.api.initialize_catalog(), {"profiles": 0})
        self.assertTrue(catalog_path.is_file())

    def test_malformed_catalog_fails_both_critical_splash_tasks(self):
        config = self.workspace.root / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "profiles.json").write_text("{not valid json", encoding="utf-8")

        with self.assertRaises(ProfileManagerError):
            self.api.initialize_catalog()
        with self.assertRaises(ProfileManagerError):
            self.api.list_profiles()

    def test_startup_warning_is_logged_once_as_a_short_single_line(self):
        raw = "first line\nsecond line " + "x" * 500
        with self.assertLogs(LOGGER_NAME, level="WARNING") as logs:
            result = self.api.report_startup_warning("preferences", raw)

        self.assertEqual(result, {"logged": True})
        self.assertEqual(len(logs.records), 1)
        expected_text = " ".join(raw.split())[:200]
        self.assertEqual(
            logs.records[0].getMessage(),
            f"Startup task preferences reported a problem: {expected_text}",
        )

    def test_unknown_startup_task_names_are_not_logged(self):
        with self.assertNoLogs(LOGGER_NAME, level="WARNING"):
            result = self.api.report_startup_warning("../../etc", "ignored")

        self.assertEqual(result, {"logged": False})


class ProductEntrypointStartupTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("startup-main-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.events = []

        index = self.workspace.child("frontend-index.html")
        index.write_text("<!doctype html>", encoding="utf-8")
        self.enterContext(patch.object(product_main, "FRONTEND_INDEX", index))
        self.enterContext(patch.object(
            product_main,
            "compose_product_candidate",
            lambda root: compose_product_candidate(root, process_inspector=_inspector()),
        ))

        original_initialize = ProfileService.initialize_metadata

        def recording_initialize(service):
            self.events.append("initialize")
            return original_initialize(service)

        self.enterContext(patch.object(ProfileService, "initialize_metadata", recording_initialize))

        def create_window(*_args, **_kwargs):
            self.events.append("create_window")
            return types.SimpleNamespace(events=_WindowEvents())

        def start(*_args, **_kwargs):
            self.events.append("start")

        fake_webview = types.SimpleNamespace(create_window=create_window, start=start)
        self.enterContext(patch.dict("sys.modules", {"webview": fake_webview}))

    def test_gui_start_opens_the_window_without_a_catalog_write(self):
        # The splash performs the catalog write after the window is shown, so the entrypoint never does it here.
        self.assertEqual(product_main.main(["--root", str(self.workspace.root)]), 0)

        self.assertEqual(self.events, ["create_window", "start"])
        self.assertFalse((self.workspace.root / "config" / "profiles.json").exists())

    def test_no_gui_start_still_publishes_the_catalog(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(product_main.main(["--root", str(self.workspace.root), "--no-gui"]), 0)

        self.assertEqual(self.events, ["initialize"])
        self.assertTrue((self.workspace.root / "config" / "profiles.json").is_file())


if __name__ == "__main__":
    unittest.main()
