"""Headless tests for the revamped GUI model and controller."""

from pathlib import Path
import unittest
from unittest.mock import Mock

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ProfileManagerError
from revamped.gui import ProfileGUIController, ProfileTableModel, TkProfileView


class StatusInspector:
    def __init__(self):
        self.open_paths = set()
        self.calls = 0

    def using_directory(self, directory, exact=False):
        self.calls += 1
        return Path(directory).absolute() in self.open_paths


class Dialogs:
    def __init__(self, confirmed=True):
        self.confirmed = confirmed
        self.warnings = []
        self.errors = []
        self.infos = []

    def warning(self, title, message):
        self.warnings.append((title, message))

    def error(self, title, message):
        self.errors.append((title, message))

    def info(self, title, message):
        self.infos.append((title, message))

    def confirm(self, title, message):
        return self.confirmed


class Scheduler:
    def __init__(self):
        self.after_calls = []
        self.cancelled = []

    def after(self, delay, callback):
        callback_id = f"callback-{len(self.after_calls)}"
        self.after_calls.append((callback_id, delay, callback))
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)


class FakeTree:
    def __init__(self):
        self.rows = {}
        self.selected = []

    def get_children(self):
        return tuple(self.rows)

    def delete(self, item):
        self.rows.pop(item, None)

    def insert(self, _parent, _index, iid, values):
        self.rows[iid] = tuple(values)

    def selection_set(self, items):
        if isinstance(items, str):
            items = [items]
        self.selected = list(items)


class GUIBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = DisposableWorkspace("r8-")
        self.workspace.__enter__()
        self.addCleanup(self.workspace.__exit__, None, None, None)
        self.paths = {
            "profile_0001": self.workspace.child("profiles", "profile_0001"),
            "profile_0002": self.workspace.child("profiles", "profile_0002"),
        }
        for path in self.paths.values():
            path.mkdir(parents=True)
        self.records = [
            {
                "profile_id": "profile_0001",
                "display_name": "Alpha",
                "profile_directory": "profiles/profile_0001",
                "created_at": "2026-09-11T00:00:00Z",
                "last_opened_at": None,
                "environment_preset": "default",
                "proxy_enabled": False,
            },
            {
                "profile_id": "profile_0002",
                "display_name": "Beta",
                "profile_directory": "profiles/profile_0002",
                "created_at": "2026-09-12T00:00:00Z",
                "last_opened_at": "2026-09-13T12:34:56Z",
                "environment_preset": "mobile",
                "proxy_enabled": True,
                "proxy_scheme": "http",
                "proxy_host": "proxy.example",
                "proxy_port": 8080,
            },
        ]
        self.profile_service = Mock()
        self.profile_service.get_profile_metadata.return_value = self.records
        self.profile_service.get_profile_dir.side_effect = self.paths.get
        self.profile_service.get_profile_record.side_effect = lambda profile_id: next(
            dict(record) for record in self.records
            if record["profile_id"] == profile_id
        )
        self.account_service = Mock()
        self.account_service.get_account.side_effect = lambda profile_id: (
            {
                "email": "alpha@example.invalid",
                "password": "synthetic-password",
                "totp_secret": "SYNTHETIC-TOTP",
            }
            if profile_id == "profile_0001" else None
        )
        self.account_service.mask_email.side_effect = lambda value: "al***@example.invalid"
        self.account_service.mask_password.side_effect = lambda value: "••••••••"
        self.account_service.mask_totp.side_effect = lambda value: "••••••"
        self.inspector = StatusInspector()

    def test_model_rows_are_cached_and_never_expose_account_secrets(self):
        model = ProfileTableModel(self.profile_service, self.account_service, self.inspector)

        model.refresh()

        self.assertEqual(model.profiles, [("profile_0001", "Alpha"), ("profile_0002", "Beta")])
        self.assertEqual(model.table_rows[0]["account"], "alpha@example.invalid")
        rendered = repr(model.table_rows)
        self.assertNotIn("synthetic-password", rendered)
        self.assertNotIn("SYNTHETIC-TOTP", rendered)
        self.assertEqual(model.table_rows[1]["environment"], "Mobile")
        self.assertEqual(model.table_rows[1]["proxy"], "On")

    def test_search_sort_and_selection_are_display_state_only(self):
        model = ProfileTableModel(self.profile_service, self.account_service, self.inspector)
        model.refresh()
        metadata_calls = self.profile_service.get_profile_metadata.call_count
        model.set_selection(["profile_0002"])

        model.set_search("alpha")
        self.assertEqual(model.profiles, [("profile_0001", "Alpha")])
        model.set_search("")
        model.sort_by("id")

        self.assertEqual(model.profiles, [("profile_0001", "Alpha"), ("profile_0002", "Beta")])
        self.assertEqual(model.selected_profiles(), [("profile_0002", "Beta")])
        self.assertEqual(self.profile_service.get_profile_metadata.call_count, metadata_calls)
        self.assertEqual(self.profile_service.get_profile_record.call_count, 0)

    def test_status_poll_uses_cached_paths_without_reloading_metadata(self):
        model = ProfileTableModel(self.profile_service, self.account_service, self.inspector)
        model.refresh()
        metadata_calls = self.profile_service.get_profile_metadata.call_count
        directory_calls = self.profile_service.get_profile_dir.call_count
        self.inspector.open_paths.add(self.paths["profile_0001"].absolute())

        self.assertTrue(model.poll_status())
        self.assertEqual(model.table_rows[0]["status"], "Open")
        self.assertEqual(self.profile_service.get_profile_metadata.call_count, metadata_calls)
        self.assertEqual(self.profile_service.get_profile_dir.call_count, directory_calls)

    def test_controller_handles_partial_multi_open_failures(self):
        dialogs = Dialogs()
        launcher = Mock()
        launcher.launch_discord.side_effect = [True, False]
        extension_service = Mock()
        extension_service.get_profile_extension_paths.return_value = []
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            launcher,
            extension_service,
            process_inspector=self.inspector,
            dialogs=dialogs,
        )
        controller.refresh()
        controller.set_selection(["profile_0001", "profile_0002"])

        result = controller.open_selected()

        self.assertEqual(result, {"requested": 1, "running": 1, "errors": []})
        self.assertEqual(launcher.launch_discord.call_count, 2)
        self.assertEqual(dialogs.errors, [])

        launcher.launch_discord.side_effect = [ProfileManagerError("synthetic launch failure"), True]
        result = controller.open_selected()
        self.assertEqual(result["requested"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(dialogs.errors), 1)

    def test_controller_preserves_partial_delete_results_and_confirmation(self):
        dialogs = Dialogs(confirmed=True)
        self.profile_service.delete_profile.side_effect = [None, ProfileManagerError("synthetic locked")]
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            dialogs=dialogs,
            process_inspector=self.inspector,
        )
        controller.refresh()
        controller.set_selection(["profile_0001", "profile_0002"])

        result = controller.delete_selected()

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(dialogs.warnings), 1)

    def test_environment_and_proxy_editors_delegate_without_auth_storage(self):
        dialogs = Dialogs()
        self.profile_service.set_environment.return_value = {"preset": "custom"}
        self.profile_service.get_proxy.return_value = {
            "enabled": False, "scheme": None, "host": None, "port": None,
        }
        self.profile_service.set_proxy.return_value = {
            "enabled": True, "scheme": "http", "host": "proxy.example", "port": 8080,
        }
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            dialogs=dialogs,
            process_inspector=self.inspector,
        )
        controller.refresh()
        controller.set_selection(["profile_0001"])

        self.assertEqual(controller.environment_editor_state()["preset"], "desktop")
        controller.save_environment("custom", {"width": 1000, "height": 700})
        controller.save_proxy(True, "http", "proxy.example", 8080)
        with self.assertRaisesRegex(ProfileManagerError, "authenticated"):
            controller.save_proxy(True, "http", "proxy.example", 8080, username="synthetic-user")

        self.profile_service.set_environment.assert_called_once()
        self.profile_service.set_proxy.assert_called_once_with(
            "profile_0001", True, "http", "proxy.example", 8080
        )

    def test_account_actions_return_masked_dialog_data_and_safe_edit_choice(self):
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            dialogs=Dialogs(),
            process_inspector=self.inspector,
        )
        controller.refresh()
        controller.set_selection(["profile_0001"])

        self.assertEqual(controller.edit_profile_action(), "view_account")
        data = controller.account_dialog_data()
        self.assertEqual(data["email"], "al***@example.invalid")
        self.assertNotIn("synthetic-password", repr(data))
        self.assertNotIn("SYNTHETIC-TOTP", repr(data))

        controller.set_selection(["profile_0002"])
        self.assertEqual(controller.edit_profile_action(), "set_account")

    def test_scheduler_callbacks_are_debounced_and_cancelled_on_shutdown(self):
        scheduler = Scheduler()
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            dialogs=Dialogs(),
            process_inspector=self.inspector,
            scheduler=scheduler,
        )
        controller.refresh()
        controller.model.set_search("be")
        controller.schedule_search()
        controller.schedule_search()
        controller._schedule_status_poll()

        controller.shutdown()

        self.assertEqual(controller._search_after_id, None)
        self.assertEqual(controller._status_after_id, None)
        self.assertEqual(scheduler.cancelled, ["callback-0", "callback-1", "callback-2"])
        self.assertTrue(controller._closing)

    def test_tk_view_renders_safe_rows_with_stable_ids(self):
        controller = ProfileGUIController(
            self.profile_service,
            self.account_service,
            dialogs=Dialogs(),
            process_inspector=self.inspector,
        )
        controller.refresh()
        tree = FakeTree()
        status = Mock()
        view = TkProfileView(controller, tree, status)

        view.render()

        self.assertEqual(tuple(tree.rows), ("profile_0001", "profile_0002"))
        self.assertEqual(tree.rows["profile_0001"][-1], "profile_0001")
        status.set.assert_called_once_with("Loaded 2 profiles")


if __name__ == "__main__":
    unittest.main()
