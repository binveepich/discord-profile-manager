"""Routing contract for the root main.py entrypoint.

main.py starts the React product by default and keeps the legacy app behind
--legacy. Both launch targets are replaced with mocks, so no window opens and
the legacy module (which configures file logging at import time) is never
imported for real.
"""

import importlib.util
import types
import unittest
from unittest.mock import Mock, call, patch

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT
from revamped import product_main


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("dpm_main_entrypoint", PROJECT_ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EntrypointRoutingTests(unittest.TestCase):
    def setUp(self):
        self.entrypoint = _load_entrypoint()
        self.workspace = DisposableWorkspace("main-entrypoint-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.root = self.workspace.root

        index = self.workspace.child("frontend-index.html")
        index.write_text("<!doctype html>", encoding="utf-8")
        self.enterContext(patch.object(product_main, "FRONTEND_INDEX", index))
        self.product_start = self.enterContext(patch.object(product_main, "main", return_value=0))

        self.legacy_start = Mock(return_value=None)
        legacy_module = types.ModuleType("legacy.profile_manager")
        legacy_module.main = self.legacy_start
        self.enterContext(patch.dict("sys.modules", {"legacy.profile_manager": legacy_module}))

    def test_default_start_hands_the_arguments_to_the_product_startup(self):
        self.assertEqual(self.entrypoint.main(["--root", str(self.root)]), 0)

        self.product_start.assert_called_once_with(["--root", str(self.root)])
        self.legacy_start.assert_not_called()

    def test_default_start_without_arguments_keeps_the_product_default_root(self):
        self.assertEqual(self.entrypoint.main([]), 0)

        self.product_start.assert_called_once_with([])

    def test_default_start_does_not_need_the_legacy_app(self):
        with patch.dict("sys.modules", {"legacy.profile_manager": None}):
            self.assertEqual(self.entrypoint.main(["--root", str(self.root)]), 0)

        self.product_start.assert_called_once_with(["--root", str(self.root)])

    def test_legacy_flag_starts_only_the_legacy_app(self):
        self.assertIsNone(self.entrypoint.main(["--legacy"]))

        self.legacy_start.assert_called_once_with()
        self.product_start.assert_not_called()

    def test_legacy_flag_refuses_other_arguments_and_starts_nothing(self):
        with self.assertRaises(SystemExit):
            self.entrypoint.main(["--legacy", "--root", str(self.root)])

        self.legacy_start.assert_not_called()
        self.product_start.assert_not_called()

    def test_missing_frontend_build_stops_with_the_build_steps(self):
        missing_index = self.workspace.child("missing", "index.html")
        with patch.object(product_main, "FRONTEND_INDEX", missing_index):
            with self.assertRaises(SystemExit) as stopped:
                self.entrypoint.main(["--root", str(self.root)])

        message = str(stopped.exception)
        self.assertIn("cd frontend", message)
        self.assertIn("npm ci", message)
        self.assertIn("npm run build", message)
        self.product_start.assert_not_called()

    def test_no_gui_and_help_do_not_need_the_frontend_build(self):
        missing_index = self.workspace.child("missing", "index.html")
        with patch.object(product_main, "FRONTEND_INDEX", missing_index):
            self.assertEqual(self.entrypoint.main(["--root", str(self.root), "--no-gui"]), 0)
            self.assertEqual(self.entrypoint.main(["--help"]), 0)

        self.assertEqual(
            self.product_start.call_args_list,
            [call(["--root", str(self.root), "--no-gui"]), call(["--help"])],
        )


if __name__ == "__main__":
    unittest.main()
