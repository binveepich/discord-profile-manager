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
            "runtime_settings": selected_count == 1,
            # Retained for headless/legacy controller callers. The visible R11
            # UI uses the single Runtime Settings action instead.
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
                    launch_paths_method = getattr(
                        type(self.extension_service),
                        "get_enabled_profile_extension_paths",
                        None,
                    )
                    if callable(launch_paths_method):
                        extension_paths = self.extension_service.get_enabled_profile_extension_paths(
                            profile_id
                        )
                    else:
                        extension_paths = self.extension_service.get_profile_extension_paths(
                            profile_id
                        )
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
        state = environment.environment_editor_state(preset, config)
        if preset == environment.ENVIRONMENT_MOBILE:
            state.update(config)
        return state

    def save_environment(self, preset, config=None):
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        result = self.profile_service.set_environment(profile_id, preset, config)
        self.refresh()
        self.set_selection([profile_id])
        self.update_status("Environment saved; close and reopen Chromium to apply supported settings.")
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
        self.update_status("Proxy saved; close and reopen Chromium to apply changes.")
        return result

    edit_proxy = proxy_editor_state

    def runtime_settings_editor_state(self):
        """Return the one coherent UI view for one selected profile."""
        selected = self.get_selected_profile()
        if not selected:
            return None
        return self.profile_service.get_runtime_settings(selected[0])

    runtime_settings_state = runtime_settings_editor_state

    def save_runtime_settings(self, environment_preset, environment_config=None, proxy_config=None):
        """Save Environment and Network together through the atomic service API."""
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        result = self.profile_service.save_runtime_settings(
            profile_id,
            environment_preset,
            environment_config,
            proxy_config,
        )
        self.refresh()
        self.set_selection([profile_id])
        self.update_status(
            "Runtime settings saved; close and reopen Chromium to apply supported settings."
        )
        return result

    def regenerate_environment(self):
        """Explicitly regenerate the selected Generated / Random identity."""
        selected = self.get_selected_profile()
        if not selected:
            return None
        profile_id, _ = selected
        result = self.profile_service.regenerate_environment(profile_id)
        self.refresh()
        self.set_selection([profile_id])
        self.update_status(
            "Generated environment regenerated; close and reopen Chromium to apply it."
        )
        return result

    def extension_manager_state(self):
        """Return the registry and effective global extension policy for the UI."""
        if self.extension_service is None:
            return {"built_ins": [], "optional": [], "extensions": [], "policy": {}}
        return self.extension_service.get_registry_state()

    def refresh_extension_registry(self):
        state = self.extension_manager_state()
        self.update_status(
            f"Extension registry refreshed: {len(state.get('extensions', []))} valid extension(s)"
        )
        return state

    def set_extension_enabled(self, extension_name, enabled):
        if self.extension_service is None:
            raise ProfileManagerError("Extension management is unavailable.")
        state = self.extension_service.set_extension_enabled(extension_name, enabled)
        action = "enabled" if enabled else "disabled"
        self.update_status(f"Extension {extension_name} {action} globally")
        return state

    def enable_extension(self, extension_name):
        return self.set_extension_enabled(extension_name, True)

    def disable_extension(self, extension_name):
        return self.set_extension_enabled(extension_name, False)

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


class TkDialogs:
    """Tk-backed dialog service kept outside the headless controller."""

    def __init__(self, root, *, messagebox_module=None, simpledialog_module=None):
        if messagebox_module is None or simpledialog_module is None:
            from tkinter import messagebox, simpledialog

            messagebox_module = messagebox_module or messagebox
            simpledialog_module = simpledialog_module or simpledialog
        self.root = root
        self.messagebox = messagebox_module
        self.simpledialog = simpledialog_module

    def warning(self, title, message):
        return self.messagebox.showwarning(title, message, parent=self.root)

    def error(self, title, message):
        return self.messagebox.showerror(title, message, parent=self.root)

    def info(self, title, message):
        return self.messagebox.showinfo(title, message, parent=self.root)

    def confirm(self, title, message):
        return self.messagebox.askyesno(title, message, parent=self.root)

    def ask_string(self, title, prompt, initialvalue=None):
        return self.simpledialog.askstring(
            title, prompt, initialvalue=initialvalue, parent=self.root
        )


class TkRevampedApp:
    """Visible disposable-mode GUI backed exclusively by a revamped controller."""

    TITLE = "Discord Profile Manager — REVAMPED DEV"

    def __init__(self, root, controller, *, allow_browser_launch=False, tk_module=None, ttk_module=None):
        self.root = root
        self.controller = controller
        self.allow_browser_launch = bool(allow_browser_launch)
        if tk_module is None:
            import tkinter as tk
            tk_module = tk
        if ttk_module is None:
            from tkinter import ttk
            ttk_module = ttk
        self.tk = tk_module
        self.ttk = ttk_module
        self.dialogs = TkDialogs(root)
        self.controller.dialogs = self.dialogs
        self.controller.scheduler = root
        self.search_var = self.tk.StringVar()
        self.status_var = self.tk.StringVar(value="Ready")
        self.sort_var = self.tk.StringVar(value="name")
        self.tree = None
        self.view = None
        self._search_render_after_id = None
        self._closing = False
        self._buttons = {}
        self._build_widgets()
        self.root.title(self.TITLE)
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def _build_widgets(self):
        tk = self.tk
        ttk = self.ttk
        self.root.geometry("1120x700")
        self.root.minsize(900, 520)

        outer = tk.Frame(self.root, padx=12, pady=10)
        outer.pack(fill=tk.BOTH, expand=True)
        header = tk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            header, text=self.TITLE, font=("Segoe UI", 16, "bold"), anchor="w"
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            text="Disposable workspace • Chromium launch disabled by default",
            fg="#8a4b08",
            anchor="e",
        ).pack(side=tk.RIGHT)

        search_bar = tk.Frame(outer)
        search_bar.pack(fill=tk.X, pady=(0, 7))
        tk.Label(search_bar, text="Search:").pack(side=tk.LEFT, padx=(0, 6))
        search_entry = tk.Entry(search_bar, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.search_var.trace_add("write", self._search_changed)
        tk.Button(search_bar, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        sort_bar = tk.Frame(outer)
        sort_bar.pack(fill=tk.X, pady=(0, 7))
        tk.Label(sort_bar, text="Sort:").pack(side=tk.LEFT, padx=(0, 5))
        for label, value in (("Name", "name"), ("ID", "id"), ("Newest", "created"), ("Default first", "default_first")):
            tk.Radiobutton(
                sort_bar,
                text=label,
                variable=self.sort_var,
                value=value,
                command=lambda selected=value: self.sort_by(selected),
            ).pack(side=tk.LEFT, padx=3)

        content = tk.Frame(outer)
        content.pack(fill=tk.BOTH, expand=True)
        table_frame = tk.Frame(content)
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        yscroll = tk.Scrollbar(table_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll = tk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree = ttk.Treeview(
            table_frame,
            columns=PROFILE_TABLE_DATA_COLUMNS,
            displaycolumns=PROFILE_TABLE_COLUMNS,
            show="headings",
            selectmode="extended",
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.config(command=self.tree.yview)
        xscroll.config(command=self.tree.xview)
        headings = {
            "name": "Name", "account": "Account", "environment": "Environment",
            "proxy": "Proxy", "status": "Status", "last_opened": "Last Opened",
            "id": "Profile ID",
        }
        widths = {
            "name": 230, "account": 210, "environment": 105, "proxy": 75,
            "status": 85, "last_opened": 150, "id": 170,
        }
        for column in PROFILE_TABLE_DATA_COLUMNS:
            self.tree.heading(
                column,
                text=headings[column],
                command=lambda selected=column: self.sort_by(selected),
            )
            self.tree.column(column, width=widths[column], anchor="w", stretch=column != "id")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-Button-1>", lambda _event: self.open_discord())

        sidebar = tk.Frame(content, width=220)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)
        self._button(sidebar, "open", "Open Discord", self.open_discord)
        self._button(sidebar, "create", "Create Profile", self.create_profile)
        self._button(sidebar, "rename", "Rename", self.rename_profile)
        self._button(sidebar, "delete", "Delete", self.delete_profile)
        tk.Frame(sidebar, height=8).pack()
        self._button(
            sidebar,
            "runtime_settings",
            "Runtime Settings…",
            self.edit_runtime_settings,
        )
        tk.Frame(sidebar, height=8).pack()
        self._button(sidebar, "extensions", "Extensions...", self.manage_extensions)
        self._button(sidebar, "set_account", "Set Synthetic Account", self.set_account)
        self._button(sidebar, "view_account", "View Account", self.view_account)
        self._button(sidebar, "remove_account", "Remove Account", self.remove_account)
        self._button(sidebar, "select_all", "Select All", self.select_all)
        self._button(sidebar, "deselect_all", "Deselect All", self.deselect_all)

        tk.Label(
            outer,
            textvariable=self.status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padx=5,
        ).pack(fill=tk.X, pady=(8, 0))
        self.view = TkProfileView(self.controller, self.tree, self.status_var)

    def _button(self, parent, key, label, command):
        button = self.tk.Button(parent, text=label, command=command, width=22, pady=4)
        button.pack(fill=self.tk.X, pady=2)
        self._buttons[key] = button

    def start(self):
        self.refresh()
        self.controller._schedule_status_poll()
        self._update_button_states()

    def _search_changed(self, *_args):
        self.controller.model.set_search(self.search_var.get())
        self.controller.schedule_search()
        if self._search_render_after_id is not None:
            try:
                self.root.after_cancel(self._search_render_after_id)
            except Exception:
                pass
        if self.search_var.get().strip():
            try:
                self._search_render_after_id = self.root.after(220, self._render)
            except Exception:
                self._search_render_after_id = None
        else:
            self._render()

    def _render(self):
        self._search_render_after_id = None
        if not self._closing and self.view is not None:
            self.view.render()
            self._update_button_states()

    def refresh(self):
        self.controller.refresh()
        self._render()

    def sort_by(self, column):
        self.controller.sort_by_column(column)
        self.sort_var.set(self.controller.model.sort_method)
        self._render()

    def _selection_changed(self, _event=None):
        visible = set(self.tree.selection())
        visible_ids = {row["profile_id"] for row in self.controller.model.table_rows}
        hidden = self.controller.model.selected_profile_ids - visible_ids
        self.controller.model.selected_profile_ids = hidden | visible
        self._update_button_states()

    def _update_button_states(self):
        state = self.controller.update_action_buttons()
        state["create"] = True
        selected = self.controller.model.selected_profiles()
        if len(selected) == 1 and self.controller.account_service is not None:
            try:
                has_account = bool(
                    self.controller.account_service.get_account(selected[0][0])
                )
            except Exception:
                has_account = False
            state.update({
                "set_account": not has_account,
                "view_account": has_account,
                "remove_account": has_account,
            })
        else:
            state.update({
                "set_account": False,
                "view_account": False,
                "remove_account": False,
            })
        normal = getattr(self.tk, "NORMAL", "normal")
        disabled = getattr(self.tk, "DISABLED", "disabled")
        for key, button in self._buttons.items():
            enabled = state.get(key, False)
            if key == "open" and not self.allow_browser_launch:
                enabled = bool(state.get("open"))
            button.config(state=normal if enabled else disabled)

    def select_all(self):
        self.controller.select_all_profiles()
        self._render()

    def deselect_all(self):
        self.controller.deselect_all_selection()
        self._render()

    def open_discord(self):
        if not self.allow_browser_launch:
            self.dialogs.info(
                "REVAMPED DEV mode",
                "Chromium launch is disabled by default in disposable development mode. "
                "No production browser or profile will be opened. Re-run with "
                "--allow-browser-launch only when you intentionally want to test the disposable runtime.",
            )
            return
        self.controller.open_selected()
        self._render()

    def create_profile(self):
        name = self.dialogs.ask_string(
            "Create Profile", "Display name (optional):"
        )
        if name is None:
            return
        self.controller.create_profile(name.strip() or None)
        self._render()

    def rename_profile(self):
        selected = self.controller.get_selected_profile()
        if not selected:
            return
        new_name = self.dialogs.ask_string(
            "Rename Profile", "New display name:", initialvalue=selected[1]
        )
        if new_name is not None and new_name.strip():
            self.controller.rename_selected(new_name)
            self._render()

    def delete_profile(self):
        self.controller.delete_selected()
        self._render()

    def set_account(self):
        if self.controller.get_selected_profile() is None:
            return
        account = self.dialogs.ask_string(
            "Synthetic Account",
            "Enter synthetic email:password[:totp] using example.invalid only:",
        )
        if account is None:
            return
        email = account.split(":", 1)[0].strip().casefold()
        if not email.endswith("@example.invalid"):
            self.dialogs.warning(
                "Synthetic Account",
                "Disposable GUI testing accepts only an email ending in @example.invalid.",
            )
            return
        try:
            self.controller.set_account(account)
            self._render()
        except Exception as error:
            self.dialogs.error("Account", f"Could not save synthetic account:\n{error}")

    def view_account(self):
        try:
            data = self.controller.account_dialog_data()
        except Exception as error:
            self.dialogs.error("Account", f"Could not read account:\n{error}")
            return
        if data is None:
            self.dialogs.info("Account", "No account is configured for this profile.")
            return
        self.dialogs.info(
            "Account (masked)",
            f"Profile: {data['display_name']}\n"
            f"Email: {data['email']}\n"
            f"Password: {data['password']}\n"
            f"TOTP: {data['totp_secret']}",
        )

    def remove_account(self):
        try:
            self.controller.remove_account()
            self._render()
        except Exception as error:
            self.dialogs.error("Account", f"Could not remove account:\n{error}")

    def manage_extensions(self):
        """Show the global extension registry and enablement policy."""
        try:
            state = self.controller.refresh_extension_registry()
        except Exception as error:
            self.dialogs.error("Extensions", f"Could not read the extension registry:\n{error}")
            return

        tk = self.tk
        dialog = tk.Toplevel(self.root)
        dialog.title("Extensions")
        dialog.transient(self.root)
        outer = tk.Frame(dialog, padx=18, pady=14)
        outer.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            outer,
            text="Global extensions for all revamped profiles",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        tk.Label(
            outer,
            text="Changes apply on the next launch of each profile.",
            wraplength=460,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 8))
        rows = tk.Frame(outer)
        rows.pack(fill=tk.BOTH, expand=True)
        created_rows = []
        normal = getattr(tk, "NORMAL", "normal")
        disabled = getattr(tk, "DISABLED", "disabled")

        def add_section(title):
            label = tk.Label(rows, text=title, font=("Segoe UI", 10, "bold"))
            label.pack(anchor="w", pady=(7, 3))
            created_rows.append(label)

        def change_extension(name, enabled, variable):
            try:
                self.controller.set_extension_enabled(name, enabled)
                variable.set(enabled)
                self.status_var.set(self.controller.status_message)
            except Exception as error:
                self.dialogs.error("Extensions", f"Could not change extension policy:\n{error}")

        def render(current_state):
            for widget in created_rows:
                try:
                    widget.destroy()
                except Exception:
                    pass
            created_rows.clear()

            add_section("Built-in")
            for item in current_state.get("built_ins", []):
                variable = tk.BooleanVar(value=True)
                text = f"{item['display_name']}    Required"
                if not item.get("available", False):
                    text += " (source missing)"
                check = tk.Checkbutton(
                    rows, text=text, variable=variable, state=disabled
                )
                check.pack(anchor="w", fill=tk.X)
                created_rows.append(check)

            add_section("Optional")
            for item in current_state.get("optional", []):
                row = tk.Frame(rows)
                row.pack(fill=tk.X, pady=1)
                created_rows.append(row)
                variable = tk.BooleanVar(value=bool(item.get("enabled")))
                check = tk.Checkbutton(
                    row, text=item["display_name"], variable=variable, state=disabled
                )
                check.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="w")
                enable = tk.Button(
                    row,
                    text="Enable",
                    width=9,
                    command=lambda name=item["name"], var=variable: change_extension(
                        name, True, var
                    ),
                )
                enable.pack(side=tk.LEFT, padx=(5, 2))
                disable = tk.Button(
                    row,
                    text="Disable",
                    width=9,
                    command=lambda name=item["name"], var=variable: change_extension(
                        name, False, var
                    ),
                )
                disable.pack(side=tk.LEFT)
                enable.config(state=disabled if item.get("enabled") else normal)
                disable.config(state=normal if item.get("enabled") else disabled)
                created_rows.extend((check, enable, disable))

            if not current_state.get("optional"):
                empty = tk.Label(rows, text="No optional extensions discovered.")
                empty.pack(anchor="w")
                created_rows.append(empty)

        render(state)
        actions = tk.Frame(outer)
        actions.pack(fill=tk.X, pady=(12, 0))
        tk.Button(
            actions,
            text="Refresh Registry",
            command=lambda: render(self.controller.refresh_extension_registry()),
        ).pack(side=tk.LEFT)
        tk.Button(actions, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        dialog.grab_set()

    def edit_runtime_settings(self):
        """Show the unified R11 Environment + Network profile settings dialog."""
        selected = self.controller.get_selected_profile()
        if not selected:
            return
        settings = self.controller.runtime_settings_editor_state()
        if settings is None:
            return

        identity = dict(settings["environment"])
        network = dict(settings["network"])
        tk = self.tk
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Profile Runtime Settings — {selected[0]}")
        dialog.transient(self.root)
        form = tk.Frame(dialog, padx=18, pady=14)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        tk.Label(
            form, text="Environment identity", font=("Segoe UI", 10, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        preset_var = tk.StringVar(value=environment.preset_label(identity["preset"]))
        tk.Label(form, text="Preset").grid(row=1, column=0, sticky="w", pady=3)
        preset_menu = self.ttk.Combobox(
            form,
            textvariable=preset_var,
            values=environment.runtime_preset_options(),
            state="readonly",
        )
        preset_menu.grid(row=1, column=1, sticky="ew", pady=3)

        identity_vars = {
            "user_agent": tk.StringVar(value=str(identity.get("user_agent") or "")),
            "language": tk.StringVar(value=str(identity.get("language") or "")),
            "device_scale_factor": tk.StringVar(
                value="" if identity.get("device_scale_factor") is None else str(identity.get("device_scale_factor"))
            ),
            "timezone": tk.StringVar(value=str(identity.get("timezone") or "")),
        }
        identity_entries = {}
        identity_labels = {
            "user_agent": "User-Agent",
            "language": "Language / locale",
            "device_scale_factor": "DPR",
            "timezone": "Timezone (metadata only — not runtime-applied)",
        }
        for row, key in enumerate(
            ("user_agent", "language", "device_scale_factor", "timezone"), 2
        ):
            tk.Label(form, text=identity_labels[key]).grid(
                row=row, column=0, sticky="w", pady=3
            )
            entry = tk.Entry(form, textvariable=identity_vars[key])
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            identity_entries[key] = entry
        touch_var = tk.BooleanVar(value=bool(identity.get("touch_mode")))
        touch_check = tk.Checkbutton(
            form, text="Request touch event support", variable=touch_var
        )
        touch_check.grid(row=6, column=1, sticky="w", pady=(1, 5))

        tk.Label(
            form, text="Browser window", font=("Segoe UI", 10, "bold")
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 5))
        policy_labels = {
            environment.WINDOW_SIZE_POLICY_SYSTEM: "Chromium default",
            environment.WINDOW_SIZE_POLICY_DESKTOP: "Desktop 1280 × 800",
            environment.WINDOW_SIZE_POLICY_CUSTOM: "Custom size",
        }
        current_policy = environment.normalize_window_size_policy(
            identity.get("window_size_policy")
        ) or environment.WINDOW_SIZE_POLICY_SYSTEM
        window_policy_var = tk.StringVar(value=policy_labels[current_policy])
        tk.Label(form, text="Window size policy").grid(
            row=8, column=0, sticky="w", pady=3
        )
        window_policy_menu = self.ttk.Combobox(
            form,
            textvariable=window_policy_var,
            values=tuple(policy_labels.values()),
            state="readonly",
        )
        window_policy_menu.grid(row=8, column=1, sticky="ew", pady=3)
        window_width_var = tk.StringVar(
            value="" if identity.get("window_width") is None else str(identity.get("window_width"))
        )
        window_height_var = tk.StringVar(
            value="" if identity.get("window_height") is None else str(identity.get("window_height"))
        )
        window_entries = {}
        for row, label, variable, key in (
            (9, "Browser window width", window_width_var, "width"),
            (10, "Browser window height", window_height_var, "height"),
        ):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = tk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            window_entries[key] = entry

        tk.Label(
            form, text="Network", font=("Segoe UI", 10, "bold")
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 5))
        mode_var = tk.StringVar(value="Enabled" if network["enabled"] else "Off")
        scheme_var = tk.StringVar(value=(network["scheme"] or "http").upper())
        host_var = tk.StringVar(value=network["host"] or "")
        port_var = tk.StringVar(
            value="" if network["port"] is None else str(network["port"])
        )
        pasted_var = tk.StringVar()
        for row, label, variable in (
            (12, "Proxy mode", mode_var),
            (13, "Proxy scheme", scheme_var),
            (14, "Proxy host", host_var),
            (15, "Proxy port", port_var),
        ):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            if label == "Proxy mode":
                widget = self.ttk.Combobox(
                    form, textvariable=variable, values=("Off", "Enabled"), state="readonly"
                )
            elif label == "Proxy scheme":
                widget = self.ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=("HTTP", "HTTPS", "SOCKS4", "SOCKS5"),
                    state="readonly",
                )
            else:
                widget = tk.Entry(form, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", pady=3)
        tk.Label(form, text="Paste proxy endpoint").grid(
            row=16, column=0, sticky="w", pady=3
        )
        tk.Entry(form, textvariable=pasted_var).grid(
            row=16, column=1, sticky="ew", pady=3
        )
        network_note = tk.StringVar(
            value="Proxy authentication is not supported or stored."
        )
        tk.Label(
            form, textvariable=network_note, wraplength=480, justify=tk.LEFT
        ).grid(row=17, column=0, columnspan=2, sticky="w", pady=(3, 5))

        tk.Label(
            form,
            text=environment.RUNTIME_SETTINGS_GUIDANCE,
            wraplength=500,
            justify=tk.LEFT,
        ).grid(row=18, column=0, columnspan=2, sticky="w", pady=(5, 4))

        custom_identity_values = {
            key: variable.get() for key, variable in identity_vars.items()
        }
        custom_identity_values["touch_mode"] = touch_var.get()
        custom_window_values = {
            "width": window_width_var.get(),
            "height": window_height_var.get(),
        }
        current_preset = environment.normalize_environment_preset(identity["preset"])
        preset_identity_values = {current_preset: dict(custom_identity_values)}
        authenticated_input = False

        def selected_policy():
            return next(
                (policy for policy, label in policy_labels.items()
                 if label == window_policy_var.get()),
                environment.WINDOW_SIZE_POLICY_SYSTEM,
            )

        def display_window_policy(_event=None):
            policy = selected_policy()
            if policy == environment.WINDOW_SIZE_POLICY_CUSTOM:
                window_width_var.set(custom_window_values["width"])
                window_height_var.set(custom_window_values["height"])
                state = tk.NORMAL
            else:
                custom_window_values["width"] = window_width_var.get()
                custom_window_values["height"] = window_height_var.get()
                if policy == environment.WINDOW_SIZE_POLICY_DESKTOP:
                    window_width_var.set(str(environment.DESKTOP_WINDOW_DEFAULTS["viewport_width"]))
                    window_height_var.set(str(environment.DESKTOP_WINDOW_DEFAULTS["viewport_height"]))
                else:
                    window_width_var.set("")
                    window_height_var.set("")
                state = tk.DISABLED
            for entry in window_entries.values():
                entry.config(state=state)

        def display_preset(_event=None):
            nonlocal current_preset, custom_identity_values
            current_values = {
                key: variable.get() for key, variable in identity_vars.items()
            }
            current_values["touch_mode"] = touch_var.get()
            preset_identity_values[current_preset] = current_values
            if current_preset == environment.ENVIRONMENT_CUSTOM:
                custom_identity_values = dict(current_values)
            current_preset = environment.normalize_environment_preset(preset_var.get())
            if current_preset == environment.ENVIRONMENT_CUSTOM:
                editor = environment.environment_editor_state(
                    current_preset, custom_identity_values
                )
            elif current_preset in preset_identity_values:
                editor = dict(preset_identity_values[current_preset])
            else:
                editor = environment.environment_editor_state(current_preset)
            for key, variable in identity_vars.items():
                variable.set("" if editor.get(key) is None else str(editor.get(key, "")))
                can_edit = current_preset == environment.ENVIRONMENT_CUSTOM or key == "timezone"
                identity_entries[key].config(
                    state=tk.NORMAL if can_edit else tk.DISABLED
                )
            touch_var.set(bool(editor.get("touch_mode", False)))
            touch_check.config(
                state=tk.NORMAL if current_preset == environment.ENVIRONMENT_CUSTOM else tk.DISABLED
            )

        def parse_proxy():
            nonlocal authenticated_input
            try:
                parsed = self.controller.parse_proxy_input(pasted_var.get())
                authenticated_input = parsed.get("authenticated") is True
                mode_var.set("Enabled")
                scheme_var.set(parsed["scheme"].upper())
                host_var.set(parsed["host"])
                port_var.set(str(parsed["port"]))
                pasted_var.set("")
                if authenticated_input:
                    network_note.set(
                        "Credentials were detected. Authentication is unsupported; Save will reject this input."
                    )
                else:
                    network_note.set("Proxy authentication is not supported or stored.")
            except Exception as error:
                self.dialogs.error("Invalid proxy", str(error))

        def regenerate():
            if environment.normalize_environment_preset(preset_var.get()) != environment.ENVIRONMENT_GENERATED:
                self.dialogs.info(
                    "Regenerate Environment",
                    "Choose Generated / Random before regenerating the environment.",
                )
                return
            try:
                refreshed = self.controller.regenerate_environment()
                new_identity = refreshed["environment"]
                for key, variable in identity_vars.items():
                    variable.set(str(new_identity.get(key) or ""))
                touch_var.set(bool(new_identity.get("touch_mode")))
                preset_identity_values[environment.ENVIRONMENT_GENERATED] = {
                    key: variable.get() for key, variable in identity_vars.items()
                }
                preset_identity_values[environment.ENVIRONMENT_GENERATED]["touch_mode"] = touch_var.get()
                policy = new_identity.get("window_size_policy")
                window_policy_var.set(policy_labels.get(policy, policy_labels[environment.WINDOW_SIZE_POLICY_SYSTEM]))
                display_window_policy()
            except Exception as error:
                self.dialogs.error("Regenerate Environment", f"Could not regenerate environment:\n{error}")

        def save():
            try:
                if mode_var.get().casefold() == "enabled" and authenticated_input:
                    raise proxy.ProxyValidationError(
                        "Authenticated proxy launch and storage are not supported. Use an unauthenticated endpoint or Proxy Off."
                    )
                environment_config = {
                    **{key: variable.get() for key, variable in identity_vars.items()},
                    "touch_mode": touch_var.get(),
                    "window_size_policy": selected_policy(),
                    "window_width": window_width_var.get(),
                    "window_height": window_height_var.get(),
                }
                proxy_config = {
                    "enabled": mode_var.get().casefold() == "enabled",
                    "scheme": scheme_var.get(),
                    "host": host_var.get(),
                    "port": port_var.get(),
                }
                self.controller.save_runtime_settings(
                    preset_var.get(), environment_config, proxy_config
                )
                dialog.destroy()
                self._render()
            except Exception as error:
                self.dialogs.error("Runtime Settings", f"Could not save runtime settings:\n{error}")

        preset_menu.bind("<<ComboboxSelected>>", display_preset)
        window_policy_menu.bind("<<ComboboxSelected>>", display_window_policy)
        display_preset()
        display_window_policy()
        tk.Button(form, text="Parse Proxy", command=parse_proxy).grid(
            row=19, column=0, sticky="w", pady=(8, 0)
        )
        tk.Button(form, text="Regenerate Environment", command=regenerate).grid(
            row=19, column=1, sticky="e", pady=(8, 0)
        )
        tk.Button(form, text="Save", command=save).grid(
            row=20, column=0, sticky="w", pady=(8, 0)
        )
        tk.Button(form, text="Cancel", command=dialog.destroy).grid(
            row=20, column=1, sticky="e", pady=(8, 0)
        )
        dialog.grab_set()

    def edit_environment(self):
        selected = self.controller.get_selected_profile()
        if not selected:
            return
        state = self.controller.environment_editor_state()
        if state is None:
            return
        tk = self.tk
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Environment — {selected[0]}")
        dialog.transient(self.root)
        form = tk.Frame(dialog, padx=18, pady=14)
        form.pack(fill=tk.BOTH, expand=True)
        preset_var = tk.StringVar(value=state["preset"].title())
        tk.Label(form, text="Preset").grid(row=0, column=0, sticky="w", pady=4)
        preset_menu = self.ttk.Combobox(
            form, textvariable=preset_var, values=("Desktop", "Mobile", "Custom"), state="readonly"
        )
        preset_menu.grid(row=0, column=1, sticky="ew", pady=4)
        variables = {}
        entries = {}
        labels = {
            "viewport_width": "Browser window width",
            "viewport_height": "Browser window height",
            "device_scale_factor": "Device scale factor",
            "language": "Browser UI language",
            "timezone": "Timezone (saved only)",
        }
        for row, key in enumerate(
            ("viewport_width", "viewport_height", "device_scale_factor", "language", "timezone"), 1
        ):
            variables[key] = tk.StringVar(value="" if state.get(key) is None else str(state.get(key)))
            tk.Label(form, text=labels[key]).grid(row=row, column=0, sticky="w", pady=3)
            entries[key] = tk.Entry(form, textvariable=variables[key])
            entries[key].grid(row=row, column=1, sticky="ew", pady=3)
        mobile_var = tk.BooleanVar(value=bool(state.get("mobile_mode")))
        touch_var = tk.BooleanVar(value=bool(state.get("touch_mode")))
        mobile_check = tk.Checkbutton(form, text="Mobile emulation (unsupported)", variable=mobile_var)
        mobile_check.grid(row=6, column=1, sticky="w")
        touch_check = tk.Checkbutton(form, text="Touch event support", variable=touch_var)
        touch_check.grid(row=7, column=1, sticky="w")
        tk.Label(
            form, text=environment.ENVIRONMENT_RUNTIME_GUIDANCE,
            wraplength=420, justify=tk.LEFT,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        custom_values = dict(state) if state["preset"] == "custom" else {}
        mobile_values = dict(state) if state["preset"] == "mobile" else {}
        current_preset = state["preset"]

        def display_preset(_event=None):
            nonlocal custom_values, current_preset
            if current_preset == "custom":
                custom_values = {
                    **{key: variable.get() for key, variable in variables.items()},
                    "mobile_mode": mobile_var.get(),
                    "touch_mode": touch_var.get(),
                }
            current_preset = preset_var.get().strip().casefold()
            editor = environment.environment_editor_state(current_preset, custom_values)
            if current_preset == "mobile" and mobile_values:
                editor.update(mobile_values)
            for key, variable in variables.items():
                variable.set(editor[key])
                editable = editor["editable"] and key != "timezone"
                entries[key].config(state=tk.NORMAL if editable else tk.DISABLED)
            mobile_var.set(editor["mobile_mode"])
            touch_var.set(editor["touch_mode"])
            mobile_check.config(state=tk.DISABLED)
            touch_check.config(state=tk.NORMAL if editor["editable"] else tk.DISABLED)

        preset_menu.bind("<<ComboboxSelected>>", display_preset)
        display_preset()

        def save():
            preset = preset_var.get().strip().casefold()
            config = {
                **{key: variable.get() for key, variable in variables.items()},
                "mobile_mode": mobile_var.get(),
                "touch_mode": touch_var.get(),
            }
            try:
                self.controller.save_environment(preset, config if preset in ("custom", "mobile") else {})
                dialog.destroy()
                self._render()
            except Exception as error:
                self.dialogs.error("Environment", f"Could not save environment:\n{error}")

        tk.Button(form, text="Save", command=save).grid(row=9, column=0, pady=(12, 0))
        tk.Button(form, text="Cancel", command=dialog.destroy).grid(row=9, column=1, pady=(12, 0))
        dialog.grab_set()

    def edit_proxy(self):
        selected = self.controller.get_selected_profile()
        if not selected:
            return
        current = self.controller.proxy_editor_state()
        tk = self.tk
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Proxy — {selected[0]}")
        dialog.transient(self.root)
        form = tk.Frame(dialog, padx=18, pady=14)
        form.pack(fill=tk.BOTH, expand=True)
        mode_var = tk.StringVar(value="Enabled" if current["enabled"] else "Off")
        scheme_var = tk.StringVar(value=(current["scheme"] or "http").upper())
        host_var = tk.StringVar(value=current["host"] or "")
        port_var = tk.StringVar(value="" if current["port"] is None else str(current["port"]))
        pasted_var = tk.StringVar()
        for row, label, variable in (
            (0, "Mode", mode_var), (1, "Scheme", scheme_var), (2, "Host", host_var), (3, "Port", port_var),
        ):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            if label == "Mode":
                widget = self.ttk.Combobox(form, textvariable=variable, values=("Off", "Enabled"), state="readonly")
            elif label == "Scheme":
                widget = self.ttk.Combobox(form, textvariable=variable, values=("HTTP", "HTTPS", "SOCKS4", "SOCKS5"), state="readonly")
            else:
                widget = tk.Entry(form, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", pady=3)
        tk.Label(form, text="Paste host:port").grid(row=4, column=0, sticky="w", pady=3)
        tk.Entry(form, textvariable=pasted_var).grid(row=4, column=1, sticky="ew", pady=3)
        note = tk.StringVar(value="Proxy authentication is not supported or stored. Close and reopen Chromium after saving changes.")
        tk.Label(form, textvariable=note, wraplength=340, justify=tk.LEFT).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        form.columnconfigure(1, weight=1)
        authenticated_input = False

        def parse():
            nonlocal authenticated_input
            try:
                parsed = self.controller.parse_proxy_input(pasted_var.get())
                authenticated_input = parsed.get("authenticated") is True
                mode_var.set("Enabled")
                scheme_var.set(parsed["scheme"].upper())
                host_var.set(parsed["host"])
                port_var.set(str(parsed["port"]))
                pasted_var.set("")
                if authenticated_input:
                    note.set("Credentials were detected. Authentication is unsupported; Save will reject this input. Parse an unauthenticated endpoint to continue.")
                else:
                    note.set("Proxy authentication is not supported or stored. Close and reopen Chromium after saving changes.")
            except Exception as error:
                self.dialogs.error("Invalid proxy", str(error))

        def save():
            try:
                if mode_var.get().casefold() == "enabled" and authenticated_input:
                    raise proxy.ProxyValidationError(
                        "Authenticated proxy launch and storage are not supported. Use an unauthenticated endpoint or Proxy Off."
                    )
                self.controller.save_proxy(
                    mode_var.get().casefold() == "enabled",
                    scheme_var.get(), host_var.get(), port_var.get(),
                )
                dialog.destroy()
                self._render()
            except Exception as error:
                self.dialogs.error("Proxy", f"Could not save proxy:\n{error}")

        tk.Button(form, text="Parse", command=parse).grid(row=6, column=0, pady=(10, 0))
        tk.Button(form, text="Save", command=save).grid(row=6, column=1, pady=(10, 0), sticky="e")
        dialog.grab_set()

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        if self._search_render_after_id is not None:
            try:
                self.root.after_cancel(self._search_render_after_id)
            except Exception:
                pass
            self._search_render_after_id = None
        self.controller.shutdown()
        try:
            self.root.destroy()
        except Exception:
            pass


__all__ = [
    "PROFILE_TABLE_COLUMNS",
    "PROFILE_TABLE_DATA_COLUMNS",
    "ProfileTableModel",
    "ProfileGUIController",
    "TkProfileView",
    "TkDialogs",
    "TkRevampedApp",
]
