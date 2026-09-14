"""M6 GUI model/display regressions without requiring a desktop session."""

import json
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

import test_m1_runtime as m1


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeTree:
    def __init__(self):
        self.rows = {}
        self.selected = []

    def get_children(self):
        return tuple(self.rows)

    def delete(self, item):
        self.rows.pop(item, None)
        self.selected = [value for value in self.selected if value != item]

    def insert(self, _parent, _index, iid, values):
        self.rows[iid] = tuple(values)

    def selection(self):
        return tuple(self.selected)

    def selection_set(self, items):
        if isinstance(items, str):
            items = [items]
        self.selected = [item for item in items if item in self.rows]

    def selection_add(self, item):
        if item in self.rows and item not in self.selected:
            self.selected.append(item)

    def selection_remove(self, items):
        if isinstance(items, str):
            items = [items]
        self.selected = [item for item in self.selected if item not in items]

    def item(self, item, option=None, **kwargs):
        if "values" in kwargs:
            self.rows[item] = tuple(kwargs["values"])
            return
        values = self.rows[item]
        return values if option == "values" else {"values": values}


class M6GUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = m1.load_manager()

    def setUp(self):
        m1.TEST_ROOT.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="m6_", dir=m1.TEST_ROOT)
        self.work = Path(self.temp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.temp.cleanup)
        self.data = self.work / "legacy" / "data"
        self.profiles = self.work / "profiles"
        self.config = self.work / "config"
        self.runtime = self.work / "browser" / "chrome.exe"
        self.extensions = self.work / "extensions"
        for name, value in {
            "DATA_DIR": self.data,
            "PROFILES_DIR": self.profiles,
            "CONFIG_DIR": self.config,
            "PROFILES_JSON": self.config / "profiles.json",
            "LOCAL_STATE": self.data / "Local State",
            "BROWSER_EXE": self.runtime,
            "EXT_DIR": self.extensions / "discord-autofill-extension",
        }.items():
            self.stack.enter_context(patch.object(self.manager, name, value))

    def make_app(self, records, accounts=None, paths=None):
        accounts = accounts or {}
        paths = paths or {}
        for profile_id in {record["profile_id"] for record in records}:
            profile_path = paths.get(profile_id, self.work / "profiles" / profile_id)
            profile_path.mkdir(parents=True, exist_ok=True)
            paths[profile_id] = profile_path

        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.root = Mock()
        app.status_var = FakeVar()
        app.search_var = FakeVar()
        app.sort_method = FakeVar("name")
        app.sort_reverse = False
        app._id_column_index = self.manager.PROFILE_TABLE_DATA_COLUMNS.index("id")
        app._search_after_id = None
        app._status_after_id = None
        app._profile_rows = []
        app._closing = False
        app.selected_profile_ids = set()
        app.table_rows = []
        app.profiles = []
        app.current_profile = None
        app.tree = FakeTree()
        app.profile_manager = Mock()
        app.profile_manager.get_profile_metadata.return_value = records
        app.profile_manager.get_profile_dir.side_effect = lambda profile_id: paths.get(
            profile_id, self.work / "missing" / profile_id
        )
        app.account_manager = Mock()
        app.account_manager.get_account.side_effect = lambda profile_id: accounts.get(profile_id)
        return app

    def test_table_columns_and_safe_metadata_display(self):
        records = [
            {
                "profile_id": "Default",
                "display_name": "Primary",
                "profile_directory": "Default",
                "created_at": "2026-09-10T00:00:00Z",
                "last_opened_at": None,
                "environment_preset": "default",
                "proxy_enabled": False,
            },
            {
                "profile_id": "profile_0001",
                "display_name": "Work",
                "profile_directory": "profile_0001",
                "created_at": "2026-09-11T00:00:00Z",
                "last_opened_at": "2026-09-13T12:34:56Z",
                "environment_preset": "default",
                "proxy_enabled": False,
            },
        ]
        accounts = {
            "profile_0001": {
                "email": "work@example.invalid",
                "password": "fixture-password",
                "totp_secret": "fixture-totp-secret",
            }
        }
        app = self.make_app(records, accounts)
        with patch.object(self.manager, "browser_using_directory", return_value=False):
            app.refresh_list()

        self.assertEqual(
            self.manager.PROFILE_TABLE_COLUMNS,
            ("name", "account", "environment", "proxy", "status", "last_opened"),
        )
        self.assertEqual(app.tree.rows["profile_0001"][:5], (
            "Work", "work@example.invalid", "Default", "Off", "Closed"
        ))
        self.assertTrue(app.tree.rows["profile_0001"][5].startswith("2026-09-13 "))
        self.assertTrue(app.tree.rows["profile_0001"][5].endswith(":34"))
        rendered = repr(app.tree.rows) + repr(app.table_rows)
        self.assertNotIn("fixture-password", rendered)
        self.assertNotIn("fixture-totp-secret", rendered)

    def test_search_and_sort_are_display_only(self):
        records = [
            {
                "profile_id": "profile_0002", "display_name": "Beta",
                "profile_directory": "profile_0002", "created_at": "2026-09-12T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
            {
                "profile_id": "profile_0001", "display_name": "Alpha",
                "profile_directory": "profile_0001", "created_at": "2026-09-11T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
        ]
        app = self.make_app(records)
        before = json.dumps(records, sort_keys=True)
        with patch.object(self.manager, "browser_using_directory", return_value=False):
            app.search_var.set("beta")
            app.refresh_list()
            self.assertEqual(list(app.tree.rows), ["profile_0002"])
            app.search_var.set("")
            app.sort_by_column("id")

        self.assertEqual(list(app.tree.rows), ["profile_0001", "profile_0002"])
        self.assertEqual(json.dumps(records, sort_keys=True), before)

    def test_search_uses_cached_rows_and_clearing_restores_them(self):
        records = [
            {
                "profile_id": "profile_0001", "display_name": "Alpha",
                "profile_directory": "profile_0001", "created_at": "2026-09-11T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
            {
                "profile_id": "profile_0002", "display_name": "Beta",
                "profile_directory": "profile_0002", "created_at": "2026-09-12T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
        ]
        app = self.make_app(records)
        with patch.object(self.manager, "browser_using_directory", return_value=False):
            app.refresh_list()
            metadata_calls = app.profile_manager.get_profile_metadata.call_count

            app.search_var.set("B")
            app._schedule_search_filter()
            app.search_var.set("Be")
            app._schedule_search_filter()
            app._run_search_filter()
            self.assertEqual(list(app.tree.rows), ["profile_0002"])
            self.assertEqual(app.profile_manager.get_profile_metadata.call_count, metadata_calls)

            app.search_var.set("")
            app._schedule_search_filter()

        self.assertEqual(list(app.tree.rows), ["profile_0001", "profile_0002"])
        self.assertEqual(app.profile_manager.get_profile_metadata.call_count, metadata_calls)
        self.assertGreaterEqual(app.root.after_cancel.call_count, 1)

    def test_status_poll_detects_both_transitions_without_full_reload(self):
        record = {
            "profile_id": "profile_0001", "display_name": "Status",
            "profile_directory": "profile_0001", "created_at": "2026-09-11T00:00:00Z",
            "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
        }
        app = self.make_app([record])
        with patch.object(self.manager, "browser_using_directory", side_effect=[True, False]):
            app.refresh_list()
            metadata_calls = app.profile_manager.get_profile_metadata.call_count
            self.assertEqual(app.tree.rows["profile_0001"][4], "Open")
            app._poll_status()

        self.assertEqual(app.tree.rows["profile_0001"][4], "Closed")
        self.assertEqual(app.profile_manager.get_profile_metadata.call_count, metadata_calls)

        app = self.make_app([record])
        with patch.object(self.manager, "browser_using_directory", side_effect=[False, True]):
            app.refresh_list()
            metadata_calls = app.profile_manager.get_profile_metadata.call_count
            self.assertEqual(app.tree.rows["profile_0001"][4], "Closed")
            app._poll_status()

        self.assertEqual(app.tree.rows["profile_0001"][4], "Open")
        self.assertEqual(app.profile_manager.get_profile_metadata.call_count, metadata_calls)

    def test_shutdown_cancels_search_and_status_callbacks(self):
        app = self.make_app([])
        app._search_after_id = "search-callback"
        app._status_after_id = "status-callback"
        app.shutdown()

        self.assertTrue(app._closing)
        self.assertIsNone(app._search_after_id)
        self.assertIsNone(app._status_after_id)
        self.assertEqual(
            app.root.after_cancel.call_args_list,
            [call("search-callback"), call("status-callback")]
        )
        after_calls = app.root.after.call_count
        with patch.object(app, "apply_search_filter") as apply_search_filter:
            app._run_search_filter()
            app._poll_status()
        apply_search_filter.assert_not_called()
        self.assertEqual(app.root.after.call_count, after_calls)

    def test_selection_is_multi_profile_and_refresh_preserves_ids(self):
        records = [
            {
                "profile_id": "profile_0001", "display_name": "One",
                "profile_directory": "profile_0001", "created_at": "2026-09-11T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
            {
                "profile_id": "profile_0002", "display_name": "Two",
                "profile_directory": "profile_0002", "created_at": "2026-09-12T00:00:00Z",
                "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
            },
        ]
        app = self.make_app(records)
        with patch.object(self.manager, "browser_using_directory", return_value=False):
            app.refresh_list()
            app.tree.selection_set(["profile_0001", "profile_0002"])
            app.on_select(None)
            self.assertIsNone(app.current_profile)
            self.assertEqual(app.selected_profile_ids, {"profile_0001", "profile_0002"})
            app.deselect_all_selection()
            self.assertEqual(app.tree.selection(), ())
            app.select_all_profiles()
            self.assertEqual(set(app.tree.selection()), {"profile_0001", "profile_0002"})
            app.profile_manager.get_profile_metadata.return_value = [records[1]]
            app.refresh_list()

        self.assertEqual(app.tree.selection(), ("profile_0002",))
        self.assertEqual(app.profiles, [("profile_0002", "Two")])

    def test_empty_and_broken_catalogs_are_safe(self):
        app = self.make_app([])
        with patch.object(self.manager, "browser_using_directory", return_value=False):
            app.refresh_list()
        self.assertEqual(app.tree.rows, {})

        app.profile_manager.get_profile_metadata.side_effect = self.manager.ProfileManagerError(
            "synthetic malformed catalog"
        )
        with patch.object(self.manager.messagebox, "showerror") as showerror:
            app.refresh_list()
        showerror.assert_called_once()
        self.assertEqual(app.profiles, [])
        self.assertEqual(app.tree.rows, {})

    def test_create_refreshes_new_profile_display(self):
        self.data.mkdir(parents=True)
        profiles = self.manager.ProfileManager()
        app = self.make_app([])
        app.profile_manager = profiles
        app.account_manager = self.manager.AccountManager(profiles)

        with patch.object(self.manager.simpledialog, "askstring", return_value="Created"), \
                patch.object(self.manager.messagebox, "askyesno", return_value=False), \
                patch.object(self.manager.messagebox, "showerror") as showerror, \
                patch.object(self.manager, "browser_using_directory", return_value=False):
            app.create_profile()

        showerror.assert_not_called()
        self.assertEqual(len(app.profiles), 1)
        profile_id, display_name = app.profiles[0]
        self.assertEqual(display_name, "Created")
        self.assertTrue(profiles.get_profile_dir(profile_id).is_dir())

    def test_edit_uses_existing_account_workflows_only(self):
        records = [{
            "profile_id": "profile_0001", "display_name": "Account",
            "profile_directory": "profile_0001", "created_at": "2026-09-11T00:00:00Z",
            "last_opened_at": None, "environment_preset": "default", "proxy_enabled": False,
        }]
        app = self.make_app(records, {"profile_0001": {"email": "a@example.invalid"}})
        with patch.object(self.manager, "browser_using_directory", return_value=False), \
                patch.object(app, "view_account") as view_account:
            app.refresh_list()
            app.tree.selection_set("profile_0001")
            app.on_select(None)
            app.edit_profile()
        view_account.assert_called_once_with()

        app.account_manager.get_account.side_effect = None
        app.account_manager.get_account.return_value = None
        with patch.object(app, "set_account_for_profile") as set_account:
            app.edit_profile()
        set_account.assert_called_once_with("profile_0001")


if __name__ == "__main__":
    unittest.main()
