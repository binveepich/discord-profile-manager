"""R9B tests for the visible disposable revamped GUI boundary."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from compatibility.fixtures import DisposableWorkspace, PROJECT_ROOT, TEST_ROOT
from revamped.core import ProjectPaths, ProfileManagerError
from revamped.gui import TkRevampedApp
from revamped.main import compose
import revamped.main as revamped_main


class R9BGuiTests(unittest.TestCase):
    def test_composition_has_only_disposable_paths(self):
        with DisposableWorkspace("r9b-paths-") as workspace:
            composition = compose(
                workspace.root,
                process_inspector=Mock(),
                process_factory=Mock(),
            )
            live_paths = ProjectPaths(PROJECT_ROOT)

            self.assertTrue(composition.paths.root.is_relative_to(TEST_ROOT.resolve()))
            self.assertNotEqual(composition.paths.profiles_json, live_paths.profiles_json)
            self.assertNotEqual(composition.paths.local_state, live_paths.local_state)
            self.assertEqual(composition.paths.browser_exe, PROJECT_ROOT / "browser" / "chrome.exe")
            self.assertEqual(composition.paths.extensions_dir, PROJECT_ROOT / "extensions")
            self.assertEqual(composition.paths.profiles_dir, workspace.root / "profiles")
            self.assertEqual(composition.paths.data_dir, workspace.root / "data")
            self.assertTrue(composition.controller.profile_service is composition.profile_service)

    def test_main_constructs_revamped_app_and_enters_mainloop_with_mocked_tk(self):
        with DisposableWorkspace("r9b-main-") as workspace:
            root = Mock()
            app = Mock()
            with patch.object(revamped_main, "_create_tk_root", return_value=root) as create_root, \
                    patch.object(revamped_main, "TkRevampedApp", return_value=app) as app_type:
                result = revamped_main.main(["--workspace-root", str(workspace.root)])

            self.assertEqual(result, 0)
            create_root.assert_called_once_with()
            app_type.assert_called_once()
            self.assertIs(app_type.call_args.args[0], root)
            self.assertFalse(app_type.call_args.kwargs["allow_browser_launch"])
            app.start.assert_called_once_with()
            root.mainloop.assert_called_once_with()
            self.assertTrue((workspace.root / "config" / "profiles.json").is_file())
            self.assertFalse((workspace.root / "browser" / "chrome.exe").exists())

    def test_tk_app_shutdown_cancels_callbacks_controller_and_root(self):
        root = Mock()
        controller = Mock()
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.root = root
        app.controller = controller
        app._search_render_after_id = "render-callback"
        app._closing = False

        app.shutdown()

        self.assertTrue(app._closing)
        root.after_cancel.assert_called_once_with("render-callback")
        controller.shutdown.assert_called_once_with()
        root.destroy.assert_called_once_with()

    def test_open_discord_is_blocked_by_default_with_clear_dev_message(self):
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.allow_browser_launch = False
        app.dialogs = Mock()
        app.controller = Mock()

        app.open_discord()

        app.dialogs.info.assert_called_once()
        message = app.dialogs.info.call_args.args[1]
        self.assertIn("disabled by default", message)
        self.assertIn("--allow-browser-launch", message)
        app.controller.open_selected.assert_not_called()

    def test_tk_action_buttons_expose_create_and_account_workflow(self):
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.tk = Mock(NORMAL="normal", DISABLED="disabled")
        app.allow_browser_launch = False
        app.controller = Mock()
        app.controller.update_action_buttons.return_value = {
            "open": True, "rename": True, "environment": True, "proxy": True,
            "delete": True, "select_all": True, "deselect_all": True,
        }
        app.controller.model.selected_profiles.return_value = [("profile_0001", "Synthetic")]
        app.controller.account_service.get_account.return_value = None
        app._buttons = {key: Mock() for key in (
            "open", "create", "rename", "delete", "environment", "proxy",
            "set_account", "view_account", "remove_account", "select_all", "deselect_all",
        )}

        app._update_button_states()

        app._buttons["create"].config.assert_called_once_with(state="normal")
        app._buttons["set_account"].config.assert_called_once_with(state="normal")
        app._buttons["view_account"].config.assert_called_once_with(state="disabled")

    def test_gui_account_entry_rejects_non_disposable_domain(self):
        app = TkRevampedApp.__new__(TkRevampedApp)
        app.controller = Mock()
        app.controller.get_selected_profile.return_value = ("profile_0001", "Synthetic")
        app.dialogs = Mock()
        app.dialogs.ask_string.return_value = "outside@example.com:synthetic-secret"

        app.set_account()

        app.dialogs.warning.assert_called_once()
        app.controller.set_account.assert_not_called()

    def test_workspace_validation_and_stable_entrypoint_remain_locked(self):
        with self.assertRaises(ProfileManagerError):
            compose(TEST_ROOT)
        with self.assertRaises(ProfileManagerError):
            compose(Path.cwd())

        stable_main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("from revamped import product_main", stable_main)
        self.assertIn('"--legacy"', stable_main)
        result = subprocess.run(
            [sys.executable, "-B", "scripts/check_refactor_integrity.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PROTECTED SOURCE INTEGRITY: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
