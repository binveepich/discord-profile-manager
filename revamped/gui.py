"""Headless-friendly GUI model/controller and optional Tk view adapter."""

from datetime import datetime
from pathlib import Path

from . import environment, proxy
from .core import ProfileManagerError
from .models import PROFILE_TABLE_COLUMNS, PROFILE_TABLE_DATA_COLUMNS
from .processes import ChromiumProcessInspector


class _NullDialogs:
    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def confirm(self, *args, **kwargs):
        return False


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class ProfileTableModel:
    """Maintain the display dataset independently from widgets or dialogs."""

    def __init__(self, profile_service, account_service=None, process_inspector=None):
        self.profile_service = profile_service
        self.account_service = account_service
        self.process_inspector = process_inspector or ChromiumProcessInspector(
            process_iter=lambda *_: []
        )
        self._profile_rows = []
        self.table_rows = []
        self.profiles = []
        self.selected_profile_ids = set()
        self.sort_method = "name"
        self.sort_reverse = False
        self.search_text = ""

    @staticmethod
    def display_environment(record):
        raw_preset = record.get("environment_preset")
        if isinstance(raw_preset, str) and raw_preset.strip().casefold() == "default":
            return "Default"
        preset, _ = environment.effective_environment(record)
        return preset.replace("_", " ").title()

    @staticmethod
    def display_proxy(record):
        return "On" if proxy.effective_proxy(record)["enabled"] else "Off"

    @staticmethod
    def display_last_opened(value):
        if not value:
            return "Never"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError):
            return str(value)

    def account_identifier(self, profile_id):
        """Return only an account identifier; never expose account secrets."""
        try:
            account = self.account_service.get_account(profile_id)
            email = account.get("email") if isinstance(account, dict) else None
            return str(email) if email else "—"
        except (AttributeError, KeyError, ProfileManagerError, OSError, TypeError):
            return "—"

    def profile_status_from_directory(self, profile_dir):
        try:
            profile_dir = Path(profile_dir)
            if not profile_dir.is_dir():
                return "Missing"
            return "Open" if self.process_inspector.using_directory(profile_dir) else "Closed"
        except (OSError, TypeError, ValueError, ProfileManagerError):
            return "Unknown"

    def profile_status(self, profile_id):
        try:
            return self.profile_status_from_directory(
                self.profile_service.get_profile_dir(profile_id)
            )
        except (AttributeError, OSError, ProfileManagerError, TypeError, ValueError):
            return "Unknown"

    def build_row(self, record):
        profile_id = str(record.get("profile_id", ""))
        display_name = str(record.get("display_name") or profile_id)
        try:
            profile_path = Path(self.profile_service.get_profile_dir(profile_id))
            status = self.profile_status_from_directory(profile_path)
        except (AttributeError, OSError, ProfileManagerError, TypeError, ValueError):
            profile_path = None
            status = "Unknown"
        last_opened_at = record.get("last_opened_at")
        return {
            "profile_id": profile_id,
            "display_name": display_name,
            "account": self.account_identifier(profile_id),
            "environment": self.display_environment(record),
            "proxy": self.display_proxy(record),
            "status": status,
            "profile_path": str(profile_path) if profile_path is not None else None,
            "last_opened": self.display_last_opened(last_opened_at),
            "created_at": str(record.get("created_at") or ""),
            "last_opened_sort": str(last_opened_at or ""),
        }

    def refresh(self):
        rows = [self.build_row(record) for record in self.profile_service.get_profile_metadata()]
        self._profile_rows = rows
        available = {row["profile_id"] for row in rows}
        self.selected_profile_ids.intersection_update(available)
        self._rebuild_visible_rows()
        return list(self.table_rows)

    def set_search(self, value):
        self.search_text = "" if value is None else str(value)
        self._rebuild_visible_rows()

    def sort_by(self, column):
        sort_method = "last_opened" if column == "last_opened" else column
        if self.sort_method == sort_method:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_method = sort_method
            self.sort_reverse = False
        self._rebuild_visible_rows()

    def _filtered_rows(self):
        search = self.search_text.strip().casefold()
        if not search:
            return list(self._profile_rows)
        return [
            row for row in self._profile_rows
            if any(search in str(row[field]).casefold() for field in (
                "profile_id", "display_name", "account", "environment",
                "proxy", "status", "last_opened",
            ))
        ]

    def _sorted_rows(self, rows):
        rows = list(rows)
        if self.sort_method == "created":
            rows.sort(key=lambda row: row["created_at"], reverse=not self.sort_reverse)
            return rows
        if self.sort_method == "default_first":
            rows.sort(
                key=lambda row: (
                    row["profile_id"] != "Default", row["display_name"].casefold()
                ),
                reverse=self.sort_reverse,
            )
            return rows
        sort_field = self.sort_method if self.sort_method in {
            "name", "id", "account", "environment", "proxy", "status", "last_opened",
        } else "name"
        key_field = {"name": "display_name", "id": "profile_id"}.get(
            sort_field, sort_field
        )
        if key_field == "last_opened":
            key_field = "last_opened_sort"
        rows.sort(key=lambda row: str(row[key_field]).casefold(), reverse=self.sort_reverse)
        return rows

    def _rebuild_visible_rows(self):
        self.table_rows = self._sorted_rows(self._filtered_rows())
        self.profiles = [
            (row["profile_id"], row["display_name"]) for row in self.table_rows
        ]

    def rows_for_display(self):
        return list(self.table_rows)

    def set_selection(self, profile_ids):
        known = {row["profile_id"] for row in self._profile_rows}
        self.selected_profile_ids = {
            profile_id for profile_id in profile_ids if profile_id in known
        }

    def select_all(self):
        self.selected_profile_ids.update(row["profile_id"] for row in self.table_rows)

    def clear_selection(self):
        self.selected_profile_ids.clear()

    def selected_profiles(self):
        names = {row["profile_id"]: row["display_name"] for row in self._profile_rows}
        return [
            (profile_id, names[profile_id])
            for profile_id in (row["profile_id"] for row in self.table_rows)
            if profile_id in self.selected_profile_ids and profile_id in names
        ]

    def selected_profile(self, dialogs=None):
        selected = self.selected_profiles()
        if not selected:
            if dialogs is not None:
                dialogs.warning("Select profile", "Please select a profile.")
            return None
        if len(selected) > 1:
            if dialogs is not None:
                dialogs.warning("Select one profile", "Please select only one profile.")
            return None
        return selected[0]

    def action_state(self):
        selected_count = len(self.selected_profiles())
        row_count = len(self.profiles)
        return {
            "open": selected_count > 0,
            "rename": selected_count == 1,
            "environment": selected_count == 1,
            "proxy": selected_count == 1,
            "delete": selected_count > 0,
            "select_all": row_count > 0,
            "deselect_all": selected_count > 0,
        }

    def poll_status(self):
        """Refresh only cached process statuses; metadata/accounts are untouched."""
        changed = False
        for row in self._profile_rows:
            status = self.profile_status_from_directory(row.get("profile_path"))
            if row.get("status") != status:
                row["status"] = status
                changed = True
        if changed:
            by_id = {row["profile_id"]: row for row in self._profile_rows}
            self.table_rows = [by_id[row["profile_id"]] for row in self.table_rows]
        return changed


class ProfileGUIController:
    """Coordinate user actions while keeping dialogs and widgets injectable."""

    def __init__(
        self,
        profile_service,
        account_service=None,
        launcher=None,
        extension_service=None,
        *,
        process_inspector=None,
        dialogs=None,
        logger=None,
        scheduler=None,
    ):
        self.profile_service = profile_service
        self.account_service = account_service
        self.launcher = launcher
        self.extension_service = extension_service
        self.dialogs = dialogs or _NullDialogs()
        self.logger = logger or _NullLogger()
        self.scheduler = scheduler
        self.model = ProfileTableModel(
            profile_service,
            account_service,
            process_inspector,
        )
        self.status_message = "Ready"
        self._search_after_id = None
        self._status_after_id = None
        self._closing = False

    @property
    def profiles(self):
        return list(self.model.profiles)

    @property
    def table_rows(self):
        return self.model.rows_for_display()

    @property
    def selected_profile_ids(self):
        return set(self.model.selected_profile_ids)

    def update_status(self, message):
        self.status_message = str(message)
        return self.status_message

    def refresh(self):
        self.update_status("Loading profiles...")
        try:
            rows = self.model.refresh()
            self.update_status(f"Loaded {len(self.model.profiles)} profiles")
            return rows
        except Exception as error:
            self.model._profile_rows = []
            self.model.table_rows = []
            self.model.profiles = []
            self.model.selected_profile_ids.clear()
            self.dialogs.error("Error", f"Could not load profiles:\n{error}")
            self.update_status("Profile list error")
            return []

    refresh_list = refresh

    def set_selection(self, profile_ids):
        self.model.set_selection(profile_ids)
        return self.model.selected_profiles()

    def select_all_profiles(self):
        self.model.select_all()
        return self.model.selected_profiles()

    def deselect_all_selection(self):
        self.model.clear_selection()
        return []

    def get_selected_profiles(self):
        return self.model.selected_profiles()

    def get_selected_profile(self):
        return self.model.selected_profile(self.dialogs)

    def on_select(self, profile_ids):
        """Accept a widget-independent selection event represented by IDs."""
        return self.set_selection(profile_ids)

    def update_action_buttons(self):
        """Return truthful action enablement for the current selection."""
        return self.model.action_state()

    def search(self, value):
        self.model.set_search(value)
        return self.table_rows

    def sort_by_column(self, column):
        self.model.sort_by(column)
        return self.table_rows

    def poll_status(self):
        if self._closing:
            return False
        changed = self.model.poll_status()
        self._schedule_status_poll()
        return changed

    def _schedule_status_poll(self):
        if self._closing or self.scheduler is None:
            return
        try:
            self._status_after_id = self.scheduler.after(1500, self.poll_status)
        except Exception:
            self._status_after_id = None

    def schedule_search(self):
        if self._closing:
            return
        if self._search_after_id is not None and self.scheduler is not None:
            try:
                self.scheduler.after_cancel(self._search_after_id)
            except Exception:
                pass
            self._search_after_id = None
        if not self.model.search_text.strip():
            self.model._rebuild_visible_rows()
            return
        if self.scheduler is None:
            self.model._rebuild_visible_rows()
            return
        try:
            self._search_after_id = self.scheduler.after(200, self.run_search)
        except Exception:
            self._search_after_id = None

    def run_search(self):
        self._search_after_id = None
        if not self._closing:
            self.model._rebuild_visible_rows()
        return self.table_rows

    def shutdown(self):
        self._closing = True
        for attribute in ("_search_after_id", "_status_after_id"):
            callback_id = getattr(self, attribute)
            if callback_id is not None and self.scheduler is not None:
                try:
                    self.scheduler.after_cancel(callback_id)
                except Exception:
                    pass
            setattr(self, attribute, None)

    def create_profile(self, display_name=None, set_account=False, account_string=None):
        try:
            profile_id = self.profile_service.create_profile(display_name)
            self.refresh()
            self.set_selection([profile_id])
            if set_account and account_string is not None and self.account_service is not None:
                self.account_service.set_account(profile_id, account_string)
            self.update_status(f"Created profile {profile_id}")
            return profile_id
        except Exception as error:
            self.dialogs.error("Error", f"Could not create profile:\n{error}")
            self.update_status("Profile creation error")
            return None

    def rename_selected(self, new_name):
        selected = self.get_selected_profile()
        if not selected or not isinstance(new_name, str) or not new_name.strip():
            return False
        profile_id, _ = selected
        try:
            self.profile_service.rename_profile(profile_id, new_name.strip())
            self.refresh()
            self.set_selection([profile_id])
            self.update_status(f"Renamed profile {profile_id}")
            return True
        except Exception as error:
            self.dialogs.error("Error", f"Could not rename profile:\n{error}")
            return False

    def delete_selected(self, confirmed=None):
        selected = self.get_selected_profiles()
        if not selected:
            self.dialogs.warning("Select profile", "Please select a profile.")
            return {"deleted": 0, "errors": []}
        if confirmed is None:
            confirmed = self.dialogs.confirm(
                "Confirm delete", f"Delete {len(selected)} profile(s)?"
            )
        if not confirmed:
            return {"deleted": 0, "errors": []}
        deleted = 0
        errors = []
        for profile_id, _ in selected:
            try:
                self.profile_service.delete_profile(profile_id)
                deleted += 1
            except Exception as error:
                errors.append(f"{profile_id}: {error}")
        self.refresh()
        self.update_status(f"Deleted {deleted} profile(s)")
        if errors:
            self.dialogs.warning("Some profiles could not be deleted", "\n\n".join(errors[:10]))
        return {"deleted": deleted, "errors": errors}

    def open_selected(self):
        selected = self.get_selected_profiles()
        if not selected:
            self.dialogs.warning("Select profile", "Please select a profile.")
            return {"requested": 0, "running": 0, "errors": []}
        requested = 0
        running = 0
        errors = []
        for profile_id, _ in selected:
            try:
                extension_paths = []
                if self.extension_service is not None:
                    extension_paths = self.extension_service.get_profile_extension_paths(profile_id)
                if self.launcher.launch_discord(profile_id, extension_paths or None):
                    requested += 1
                else:
                    running += 1
            except Exception as error:
                errors.append(f"{profile_id}: {error}")
        self.refresh()
        result = {"requested": requested, "running": running, "errors": errors}
        self.update_status(
            f"Launch requested: {requested}; already running: {running}; failed: {len(errors)}"
        )
        if errors:
            self.dialogs.error("Could not open some profiles", "\n\n".join(errors[:10]))
        return result

    def edit_profile_action(self):
        selected = self.get_selected_profile()
        if not selected or self.account_service is None:
            return None
        profile_id, _ = selected
        try:
            account = self.account_service.get_account(profile_id)
        except Exception as error:
            self.dialogs.error("Error", f"Could not edit profile account:\n{error}")
            return None
        return "view_account" if account else "set_account"

    edit_profile = edit_profile_action

    def environment_editor_state(self):
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        record = self.profile_service.get_profile_record(profile_id)
        preset, config = environment.effective_environment(record)
        return environment.environment_editor_state(preset, config)

    def save_environment(self, preset, config=None):
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        result = self.profile_service.set_environment(profile_id, preset, config)
        self.refresh()
        self.set_selection([profile_id])
        return result

    edit_environment = environment_editor_state

    def proxy_editor_state(self):
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        return self.profile_service.get_proxy(profile_id)

    def parse_proxy_input(self, value):
        return proxy.parse_proxy_string(value)

    def save_proxy(self, enabled, scheme=None, host=None, port=None, username=None, password=None):
        selected = self.get_selected_profile()
        if not selected:
            return None
        if username or password:
            raise proxy.ProxyValidationError(
                "Proxy authentication was parsed, but authenticated proxy launch and storage are not supported."
            )
        profile_id, _ = selected
        result = self.profile_service.set_proxy(profile_id, enabled, scheme, host, port)
        self.refresh()
        self.set_selection([profile_id])
        return result

    edit_proxy = proxy_editor_state

    def account_dialog_data(self):
        selected = self.get_selected_profile()
        if not selected or self.account_service is None:
            return None
        profile_id, display_name = selected
        account = self.account_service.get_account(profile_id)
        if not account:
            return None
        return {
            "profile_id": profile_id,
            "display_name": display_name,
            "email": self.account_service.mask_email(account["email"]),
            "password": self.account_service.mask_password(account["password"]),
            "totp_secret": self.account_service.mask_totp(account["totp_secret"]),
        }

    def set_account(self, account_string):
        selected = self.get_selected_profile()
        if not selected or self.account_service is None:
            return False
        self.account_service.set_account(selected[0], account_string)
        self.refresh()
        self.set_selection([selected[0]])
        return True

    def remove_account(self, confirmed=None):
        selected = self.get_selected_profile()
        if not selected or self.account_service is None:
            return False
        if confirmed is None:
            confirmed = self.dialogs.confirm(
                "Confirm account removal",
                f"Remove account from profile '{selected[1]}'?",
            )
        if not confirmed:
            return False
        self.account_service.remove_account(selected[0])
        self.refresh()
        self.set_selection([selected[0]])
        return True

    open_discord = open_selected
    delete_profile = delete_selected
    rename_profile = rename_selected


class TkProfileView:
    """Small optional renderer for a ttk.Treeview-like widget.

    Full dialog construction remains a presentation concern. The adapter is
    intentionally tiny so a real Tk window is never needed by model tests.
    """

    def __init__(self, controller, tree, status_var=None):
        self.controller = controller
        self.tree = tree
        self.status_var = status_var

    def render(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.controller.table_rows:
            self.tree.insert(
                "", "end", iid=row["profile_id"], values=(
                    row["display_name"], row["account"], row["environment"],
                    row["proxy"], row["status"], row["last_opened"],
                    row["profile_id"],
                )
            )
        selected = [
            row["profile_id"] for row in self.controller.table_rows
            if row["profile_id"] in self.controller.selected_profile_ids
        ]
        if selected:
            self.tree.selection_set(selected)
        if self.status_var is not None:
            self.status_var.set(self.controller.status_message)
        return self.controller.table_rows


__all__ = [
    "PROFILE_TABLE_COLUMNS",
    "PROFILE_TABLE_DATA_COLUMNS",
    "ProfileTableModel",
    "ProfileGUIController",
    "TkProfileView",
]
