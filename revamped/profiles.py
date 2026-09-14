"""Disposable-root profile lifecycle and compatibility service."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from . import environment, proxy
from .core import (
    MANAGER_PATH_KEY,
    NEW_PROFILE_PATTERN,
    ProfileManagerError,
    ProfileNotFoundError,
    checked_path,
    ensure_tree_has_no_links,
    metadata_path_for_profile,
    profile_path_from_metadata,
    validate_candidate_profile_name,
    validate_manager_path,
    validate_profile_id,
)
from .models import (
    DEFAULT_ENVIRONMENT_PRESET,
    METADATA_VERSION,
    new_profile_record,
    profile_pairs,
    timestamp_from_epoch,
    utc_timestamp,
)
from .storage import LegacyStateStore, MirrorCoordinator, ProfileCatalogStore, empty_catalog
from .processes import ChromiumProcessInspector


PROFILE_EXTENSION_DIR_NAME = "Unpacked Extensions"


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class ProfileService:
    """Own profile catalog orchestration without Tk or module-global paths."""

    def __init__(
        self,
        paths,
        *,
        catalog_store=None,
        legacy_store=None,
        process_inspector=None,
        logger=None,
        clock=None,
    ):
        self.paths = paths
        self.catalog_store = catalog_store or ProfileCatalogStore(paths, logger)
        self.metadata = self.catalog_store
        self.legacy_store = legacy_store or LegacyStateStore(paths, logger)
        self.local_state = self.legacy_store
        self.process_inspector = process_inspector or ChromiumProcessInspector()
        self.logger = logger or _NullLogger()
        self.clock = clock
        self._legacy_mirror_enabled = self.legacy_store.path.exists()
        self._unpublished_paths = set()
        self._operation_depth = 0

    @contextmanager
    def operation(self):
        with self.legacy_store.operation():
            self._operation_depth += 1
            try:
                yield
            finally:
                self._operation_depth -= 1

    @staticmethod
    def _empty_catalog():
        return empty_catalog()

    def _record(self, profile_id, display_name, profile_path, created_at=None, last_opened_at=None):
        return new_profile_record(
            profile_id,
            display_name,
            profile_path,
            self.paths,
            created_at=created_at,
            last_opened_at=last_opened_at,
            clock=self.clock,
        ).to_mapping()

    @staticmethod
    def _record_map(data):
        return {record["profile_id"]: record for record in data["profiles"]}

    def _legacy_record(self, profile_id, info):
        if not isinstance(info, dict):
            raise ProfileManagerError(f"Invalid legacy profile metadata for {profile_id}.")
        manager_path = info.get(MANAGER_PATH_KEY)
        if manager_path is not None:
            manager_path = validate_manager_path(manager_path)
            profile_path = checked_path(self.paths.profiles_dir / manager_path, self.paths.profiles_dir)
        else:
            profile_path = checked_path(self.paths.data_dir / profile_id, self.paths.data_dir)
        display_name = info.get("name", profile_id)
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = profile_id
        return self._record(
            profile_id,
            display_name,
            profile_path,
            created_at=timestamp_from_epoch(info.get("created", 0), self.clock),
            last_opened_at=info.get("last_opened_at") if isinstance(info.get("last_opened_at"), str) else None,
        )

    @staticmethod
    def _looks_like_profile_directory(path):
        return path.is_dir() and (
            (path / "Default" / "Preferences").is_file()
            or (path / "Preferences").is_file()
        )

    def _scan_profile_root(self, root):
        found = []
        root = Path(root)
        if not root.is_dir():
            return found
        for path in root.iterdir():
            if path.name in (".manager.lock", "Local State") or path.name.startswith("."):
                continue
            if root.absolute() == self.paths.profiles_dir.absolute() and not NEW_PROFILE_PATTERN.fullmatch(path.name):
                continue
            if not validate_candidate_profile_name(path.name):
                continue
            try:
                checked_path(path, root)
            except ProfileManagerError:
                continue
            if self._looks_like_profile_directory(path) and path.absolute() not in self._unpublished_paths:
                found.append(path)
        return found

    def _read_legacy_catalog_for_bootstrap(self, managed_paths, legacy_paths):
        if self.legacy_store.path.exists():
            try:
                return self.legacy_store.load()
            except ProfileManagerError:
                if not managed_paths and not legacy_paths:
                    raise
                self.logger.warning("Legacy compatibility state could not be read; using physical profiles")
                return self.legacy_store._create_default()
        if not managed_paths and not legacy_paths:
            state = self.legacy_store.load()
        else:
            state = self.legacy_store._create_default()
        self.legacy_store.save(state)
        self._legacy_mirror_enabled = True
        return state

    def _bootstrap_catalog(self):
        managed_paths = self._scan_profile_root(self.paths.profiles_dir)
        legacy_paths = self._scan_profile_root(self.paths.data_dir)
        legacy_state = self._read_legacy_catalog_for_bootstrap(managed_paths, legacy_paths)
        catalog = self._empty_catalog()
        known_ids = set()
        known_directories = set()
        cache = legacy_state.get("profile", {}).get("info_cache", {})
        for profile_id, info in cache.items():
            record = self._legacy_record(profile_id, info)
            directory_key = record["profile_directory"].casefold()
            if record["profile_id"].casefold() in known_ids or directory_key in known_directories:
                raise ProfileManagerError("Duplicate profile metadata in the legacy state.")
            catalog["profiles"].append(record)
            known_ids.add(record["profile_id"].casefold())
            known_directories.add(directory_key)
        for path in [*managed_paths, *legacy_paths]:
            profile_id = path.name
            folded_id = profile_id.casefold()
            directory_key = metadata_path_for_profile(path, self.paths).casefold()
            if directory_key in known_directories or folded_id in known_ids:
                continue
            catalog["profiles"].append(self._record(profile_id, profile_id, path))
            known_ids.add(folded_id)
            known_directories.add(directory_key)
        self.catalog_store.save(catalog)
        self._legacy_mirror_enabled = True
        return catalog

    def _reconcile_managed_profiles(self, catalog):
        known_ids = {record["profile_id"].casefold() for record in catalog["profiles"]}
        known_directories = {record["profile_directory"].casefold() for record in catalog["profiles"]}
        changed = False
        for path in self._scan_profile_root(self.paths.profiles_dir):
            directory_key = metadata_path_for_profile(path, self.paths).casefold()
            if directory_key in known_directories:
                continue
            matching = next((record for record in catalog["profiles"] if record["profile_id"].casefold() == path.name.casefold()), None)
            if matching is not None:
                old_path = profile_path_from_metadata(matching["profile_directory"], self.paths)
                if not old_path.exists():
                    matching["profile_directory"] = metadata_path_for_profile(path, self.paths)
                    changed = True
                continue
            if path.name.casefold() in known_ids:
                continue
            catalog["profiles"].append(self._record(path.name, path.name, path))
            known_ids.add(path.name.casefold())
            known_directories.add(directory_key)
            changed = True
        return changed

    def _reconcile_legacy_profiles(self, catalog):
        if not self.legacy_store.path.exists():
            return False
        try:
            legacy_state = self.legacy_store.load()
        except ProfileManagerError:
            self.logger.warning("Ignoring unreadable legacy state after catalog initialization")
            return False
        known_ids = {record["profile_id"].casefold() for record in catalog["profiles"]}
        known_directories = {record["profile_directory"].casefold() for record in catalog["profiles"]}
        changed = False
        for profile_id, info in legacy_state.get("profile", {}).get("info_cache", {}).items():
            if profile_id.casefold() in known_ids:
                continue
            record = self._legacy_record(profile_id, info)
            if record["profile_directory"].casefold() in known_directories:
                continue
            catalog["profiles"].append(record)
            known_ids.add(profile_id.casefold())
            known_directories.add(record["profile_directory"].casefold())
            changed = True
        return changed

    def _load_catalog(self):
        catalog = self.catalog_store.load()
        if catalog is None:
            return self._bootstrap_catalog()
        changed = self._reconcile_legacy_profiles(catalog)
        changed = self._reconcile_managed_profiles(catalog) or changed
        if changed:
            self._save_catalog(catalog)
        return catalog

    def initialize_metadata(self):
        with self.operation():
            self._check_registry_idle()
            self._load_catalog()

    def get_profile_metadata(self):
        return [dict(record) for record in self._load_catalog()["profiles"]]

    def get_profile_record(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        record = self._record_map(self._load_catalog()).get(profile_id)
        if record is None:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        return dict(record)

    def get_environment(self, profile_id):
        record = self.get_profile_record(profile_id)
        preset, config = environment.effective_environment(record)
        return {"preset": preset, "environment_preset": preset, **dict(config)}

    def set_environment(self, profile_id, preset, config=None):
        profile_id = validate_profile_id(profile_id)
        normalized_preset = environment.normalize_environment_preset(preset)
        normalized_config = environment.normalize_environment_config(config)
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record["environment_preset"] = normalized_preset
            record.pop("environment_config", None)
            if normalized_preset == environment.ENVIRONMENT_CUSTOM:
                record["environment_config"] = normalized_config or {}
            elif normalized_preset == environment.ENVIRONMENT_MOBILE and normalized_config:
                mobile_config = {key: normalized_config[key] for key in (
                    "viewport_width", "viewport_height", "device_scale_factor", "language", "timezone"
                ) if key in normalized_config}
                if mobile_config:
                    record["environment_config"] = mobile_config
            self._save_catalog(catalog)
        return self.get_environment(profile_id)

    set_environment_preset = set_environment

    def get_proxy(self, profile_id):
        return dict(proxy.effective_proxy(self.get_profile_record(profile_id)))

    def set_proxy(self, profile_id, enabled, scheme=None, host=None, port=None):
        profile_id = validate_profile_id(profile_id)
        if enabled is not True and enabled is not False:
            raise proxy.ProxyValidationError("Proxy state must be Enabled or Off.")
        normalized = None
        if enabled:
            normalized = proxy.normalize_proxy_config(scheme, host, port)
            if proxy.normalize_proxy_scheme(scheme) is None:
                raise proxy.ProxyValidationError("Unsupported proxy scheme. Choose HTTP, HTTPS, SOCKS4, or SOCKS5.")
            if proxy.normalize_proxy_host(host) is None:
                raise proxy.ProxyValidationError("Proxy host must be a hostname or IP address without a scheme, port, path, or credentials.")
            if proxy.normalize_proxy_port(port) is None:
                raise proxy.ProxyValidationError("Proxy port must be a number from 1 to 65535.")
            if normalized is None:
                raise proxy.ProxyValidationError("Proxy configuration is incomplete or invalid.")
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            if not enabled:
                record["proxy_enabled"] = False
                for field in ("proxy_scheme", "proxy_host", "proxy_port"):
                    record.pop(field, None)
            else:
                record["proxy_enabled"] = True
                record.update({"proxy_scheme": normalized["scheme"], "proxy_host": normalized["host"], "proxy_port": normalized["port"]})
            self._save_catalog(catalog)
        return self.get_proxy(profile_id)

    def _legacy_info_for_record(self, record, existing=None):
        info = dict(existing or {})
        info["name"] = record["display_name"]
        try:
            info["created"] = int(datetime.fromisoformat(record["created_at"].replace("Z", "+00:00")).timestamp())
        except (AttributeError, TypeError, ValueError, OverflowError):
            info["created"] = 0
        path = profile_path_from_metadata(record["profile_directory"], self.paths)
        if path.absolute().is_relative_to(self.paths.profiles_dir.absolute()):
            info[MANAGER_PATH_KEY] = path.name
        else:
            info.pop(MANAGER_PATH_KEY, None)
        return info

    def _save_catalog(self, catalog):
        coordinator = MirrorCoordinator(
            self.catalog_store, self.legacy_store, self._legacy_mirror_enabled, self.logger
        )
        coordinator.save(catalog)
        self._legacy_mirror_enabled = coordinator.enabled

    def _check_registry_idle(self):
        for root, label in ((self.paths.data_dir, "legacy"), (self.paths.profiles_dir, "managed")):
            if self.process_inspector.using_directory(root, exact=True):
                raise ProfileManagerError(f"Chromium is using the shared {label} data directory. Close it before using the manager.")

    def get_profiles(self):
        return profile_pairs(self._load_catalog()["profiles"])

    def next_profile_id(self, cache):
        max_num = 0
        candidates = list(cache) if isinstance(cache, dict) else []
        for info in cache.values() if isinstance(cache, dict) else []:
            if not isinstance(info, dict):
                continue
            if isinstance(info.get(MANAGER_PATH_KEY), str):
                candidates.append(info[MANAGER_PATH_KEY])
            if isinstance(info.get("profile_directory"), str):
                try:
                    candidates.append(profile_path_from_metadata(info["profile_directory"], self.paths).name)
                except ProfileManagerError:
                    pass
        for root in (self.paths.profiles_dir, self.paths.data_dir):
            if root.is_dir():
                candidates.extend(path.name for path in root.iterdir())
        for candidate in candidates:
            match = NEW_PROFILE_PATTERN.fullmatch(candidate)
            if match:
                max_num = max(max_num, int(match.group(1)))
                continue
            pending = re.match(r"^\.deleting-(profile_\d+)-", candidate, re.IGNORECASE)
            if pending:
                max_num = max(max_num, int(pending.group(1).split("_", 1)[1]))
        return f"profile_{max_num + 1:04d}"

    def _resolve_profile_dir(self, profile_id, record=None):
        profile_id = validate_profile_id(profile_id)
        if record is not None and "profile_directory" in record:
            return profile_path_from_metadata(record["profile_directory"], self.paths)
        if record is not None and MANAGER_PATH_KEY in record:
            return checked_path(self.paths.profiles_dir / validate_manager_path(record[MANAGER_PATH_KEY]), self.paths.profiles_dir)
        legacy_path = checked_path(self.paths.data_dir / profile_id, self.paths.data_dir)
        if legacy_path.exists() or not NEW_PROFILE_PATTERN.fullmatch(profile_id):
            return legacy_path
        return checked_path(self.paths.profiles_dir / profile_id, self.paths.profiles_dir)

    def get_profile_dir(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        catalog = self.catalog_store.load()
        if catalog is None and not self.legacy_store.path.exists() and not self.paths.data_dir.exists() and not self.paths.profiles_dir.exists():
            return self._resolve_profile_dir(profile_id)
        record = self._record_map(self._load_catalog()).get(profile_id)
        return self._resolve_profile_dir(profile_id, record) if record is not None else self._resolve_profile_dir(profile_id)

    def _check_pending_delete(self, profile_id, parent=None):
        roots = [parent] if parent is not None else [self.paths.data_dir, self.paths.profiles_dir]
        for root in roots:
            if not root or not Path(root).exists():
                continue
            for path in Path(root).iterdir():
                if path.name.startswith(f".deleting-{profile_id}-"):
                    raise ProfileManagerError(f"An interrupted deletion left data at {path}. Restore or inspect that directory before continuing.")

    def require_profile_dir(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        if (self.catalog_store.load() is None and not self.legacy_store.path.exists() and not self.paths.data_dir.exists() and not self.paths.profiles_dir.exists()):
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        record = self._record_map(self._load_catalog()).get(profile_id)
        if record is None:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        path = self._resolve_profile_dir(profile_id, record)
        if not path.is_dir():
            self._check_pending_delete(profile_id, path.parent)
            raise ProfileNotFoundError(f"Profile directory is missing or invalid: {path}. Restore it before opening; no replacement profile was created.")
        return path

    def _initialize_profile_structure(self, profile_id):
        profile_dir = self._resolve_profile_dir(profile_id)
        profile_dir.parent.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(exist_ok=False)
        browser_profile = profile_dir / "Default"
        browser_profile.mkdir()
        prefs_file = browser_profile / "Preferences"
        if not prefs_file.exists():
            prefs_file.write_text(json.dumps({
                "profile": {"name": profile_id},
                "extensions": {"ui": {"developer_mode": True}},
            }, indent=2), encoding="utf-8")
        (profile_dir / PROFILE_EXTENSION_DIR_NAME).mkdir(exist_ok=True)

    def create_profile(self, display_name=None):
        if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
            raise ProfileManagerError("Profile name must not be empty.")
        with self.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            new_id = self.next_profile_id(self._record_map(catalog))
            self._initialize_profile_structure(new_id)
            profile_dir = self._resolve_profile_dir(new_id)
            catalog["profiles"].append(self._record(new_id, display_name.strip() if display_name is not None else new_id, profile_dir))
            try:
                self._save_catalog(catalog)
            except Exception:
                self._unpublished_paths.add(profile_dir.absolute())
                raise
            return new_id

    def rename_profile(self, profile_id, new_name):
        if not isinstance(new_name, str) or not new_name.strip():
            raise ProfileManagerError("Profile name must not be empty.")
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record["display_name"] = new_name.strip()
            self._save_catalog(catalog)

    def delete_profile(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        with self.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found")
            profile_dir = self._resolve_profile_dir(profile_id, record)
            if self.process_inspector.using_directory(profile_dir):
                raise ProfileManagerError(f"Close Chromium for {profile_id} before deleting it.")
            pending = None
            if profile_dir.exists():
                if not profile_dir.is_dir():
                    raise ProfileManagerError(f"Profile path is not a directory: {profile_dir}")
                pending = checked_path(profile_dir.parent / f".deleting-{profile_id}-{uuid.uuid4().hex}", profile_dir.parent)
                profile_dir.rename(pending)
            else:
                self._check_pending_delete(profile_id, profile_dir.parent)
            catalog["profiles"] = [item for item in catalog["profiles"] if item["profile_id"] != profile_id]
            try:
                self._save_catalog(catalog)
            except Exception:
                if pending is not None:
                    if profile_dir.exists():
                        raise ProfileManagerError(f"Deletion was interrupted. Profile data is preserved at {pending}.")
                    pending.rename(profile_dir)
                raise
            if pending is not None:
                checked_path(pending, pending.parent)
                try:
                    shutil.rmtree(pending)
                except OSError as error:
                    raise ProfileManagerError(f"Profile was removed from the list, but some data could not be deleted at {pending}. No further cleanup will run automatically.") from error

    def migrate_profile(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        with self.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            current_path = self._resolve_profile_dir(profile_id, record)
            if current_path.absolute().is_relative_to(self.paths.profiles_dir.absolute()):
                if not current_path.is_dir():
                    raise ProfileManagerError(f"Profile {profile_id} is marked as migrated, but its managed directory is missing: {current_path}.")
                return current_path.name
            source = checked_path(self.paths.data_dir / profile_id, self.paths.data_dir)
            if not source.exists():
                self._check_pending_delete(profile_id, source.parent)
                raise ProfileManagerError(f"Legacy profile directory is missing: {source}. No migration was performed.")
            if not source.is_dir():
                raise ProfileManagerError(f"Legacy profile path is not a directory: {source}. No migration was performed.")
            if self.process_inspector.using_directory(source):
                raise ProfileManagerError(f"Close Chromium for {profile_id} before migrating it.")
            destination = None
            try:
                ensure_tree_has_no_links(source)
                checked_path(self.paths.profiles_dir, self.paths.root)
                self.paths.profiles_dir.mkdir(parents=True, exist_ok=True)
                new_id = self.next_profile_id(self._record_map(catalog))
                destination = checked_path(self.paths.profiles_dir / new_id, self.paths.profiles_dir)
                if destination.exists():
                    raise ProfileManagerError(f"Cannot migrate {profile_id}: destination already exists at {destination}.")
                shutil.copytree(source, destination)
            except ProfileManagerError:
                raise
            except (OSError, shutil.Error) as error:
                raise ProfileManagerError(f"Profile migration failed. The legacy source was left untouched. A partial copy may remain.") from error
            try:
                record["profile_directory"] = metadata_path_for_profile(destination, self.paths)
                self._save_catalog(catalog)
            except Exception as error:
                self._unpublished_paths.add(destination.absolute())
                raise ProfileManagerError(f"Profile data was copied to {destination}, but metadata could not be updated. The legacy source remains untouched; remove nothing automatically.") from error
            return new_id

    def mark_profile_opened(self, profile_id, catalog=None):
        if self._operation_depth:
            catalog = catalog or self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record["last_opened_at"] = utc_timestamp(self.clock)
            self._save_catalog(catalog)
            return
        with self.operation():
            self._check_registry_idle()
            catalog = catalog or self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record["last_opened_at"] = utc_timestamp(self.clock)
            self._save_catalog(catalog)

    def get_browser_profile_dir(self, profile_id):
        root = self.require_profile_dir(profile_id)
        flat_markers = ("Cookies", "Network", "Local Storage", "IndexedDB", "Login Data", "History", "Bookmarks", "Sessions", "Session Storage", "Web Data", "Service Worker")
        if any((root / marker).exists() for marker in flat_markers):
            raise ProfileManagerError(f"Legacy browser data is directly inside {root}. This appears to be a shared-root subprofile, not an isolated user-data directory.")
        browser_state = checked_path(root / "Local State", root)
        last_used = "Default"
        if browser_state.exists():
            try:
                data = json.loads(browser_state.read_text(encoding="utf-8-sig"), object_pairs_hook=LegacyStateStore._unique_keys)
                if not isinstance(data, dict) or not isinstance(data.get("profile", {}), dict):
                    raise ValueError("Invalid browser Local State")
                last_used = validate_profile_id(data.get("profile", {}).get("last_used", "Default"))
            except (OSError, ValueError, UnicodeError) as error:
                raise ProfileManagerError(f"Cannot read Chromium state at {browser_state}. Restore it before opening this profile.") from error
        browser_profile = checked_path(root / last_used, root)
        if last_used != "Default" and not browser_profile.is_dir():
            raise ProfileManagerError(f"Chromium's last-used profile directory is missing: {browser_profile}")
        if not browser_profile.exists():
            for child in root.iterdir():
                if child.is_dir() and child.name != PROFILE_EXTENSION_DIR_NAME and (child / "Preferences").exists():
                    raise ProfileManagerError(f"Ambiguous Chromium profile layout at {root}. No new profile will be created.")
        elif not browser_profile.is_dir():
            raise ProfileManagerError(f"Chromium profile path is not a directory: {browser_profile}")
        checked_path(browser_profile / "Preferences", root)
        return browser_profile


ProfileManager = ProfileService
