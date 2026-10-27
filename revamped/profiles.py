"""Disposable-root profile lifecycle and compatibility service."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import time
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
MAX_DISPLAYED_PROFILES = 9_999
# Owner-approved one-time baseline when STT was first stored: this profile goes last.
BASELINE_LAST_PROFILE_ID = "profile_0047"
_TYPED_NUMBER_NAME = re.compile(r"\s*([0-9]+)\s*\|")
_DEFAULT_PROFILE_NAME = re.compile(r"\s*Profile\s+(\d+)\s*")
_PROFILE_ID_NUMBER = re.compile(r"(\d+)$")


def profile_display_sort_key(display_name, profile_id):
    """Return the old name-rule (group, number) key; lower sorts first. Used only to freeze the first stored STT.

    Group 0: a typed STT-style prefix such as "0001 | name", ordered by that number.
    Group 1: plain account names, in catalog order.
    Group 2: a name containing FLAG in any case, ordered by the profile's own number.
    Group 3: the default "Profile N" name, ordered by N.
    """
    name = str(display_name or "")
    typed = _TYPED_NUMBER_NAME.match(name)
    if typed:
        return 0, int(typed.group(1))
    if "flag" in name.casefold():
        number = _PROFILE_ID_NUMBER.search(str(profile_id))
        return 2, int(number.group(1)) if number else 0
    default = _DEFAULT_PROFILE_NAME.fullmatch(name)
    if default:
        return 3, int(default.group(1))
    return 1, 0


def _usable_stt(value):
    """Return a stored STT that can be used as a position, or None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _name_order(records):
    """Return records in the old name-based order. Used only to freeze the first stored STT."""
    return sorted(
        records,
        key=lambda record: profile_display_sort_key(
            record.get("display_name") or record["profile_id"], record["profile_id"]
        ),
    )


def table_order(records):
    """Return (STT, record) pairs in table order, sorted by the stored STT and never by display name.

    Records sort by stored STT, then by profile_id. A record with no usable STT sorts after the numbered
    rows. The STT shown is the 1-based position, which equals the stored value once the catalog is 1..N.
    """
    ordered = sorted(
        records,
        key=lambda record: (
            _usable_stt(record.get("stt")) is None,
            _usable_stt(record.get("stt")) or 0,
            record["profile_id"],
        ),
    )
    return list(enumerate(ordered, 1))


def next_stt(records):
    """Return the STT for a new record: one past the highest stored STT."""
    return max((_usable_stt(record.get("stt")) or 0 for record in records), default=0) + 1


def compact_stt(records):
    """Renumber records 1..N in their current table order, so a delete leaves no gap."""
    for position, record in table_order(records):
        record["stt"] = position


def assign_missing_stt(records):
    """Give each record without a usable STT one, in place. Runs at the startup schema point.

    With no STT stored yet, this is the one-time baseline: the old name-based order, with the approved profile
    moved to the end. Otherwise only unnumbered records are touched, and they are appended after the highest STT.
    """
    if not any(_usable_stt(record.get("stt")) for record in records):
        ordered = sorted(
            _name_order(records), key=lambda record: record["profile_id"] == BASELINE_LAST_PROFILE_ID
        )
        for position, record in enumerate(ordered, 1):
            record["stt"] = position
        return
    number = next_stt(records)
    for record in records:
        if _usable_stt(record.get("stt")) is None:
            record["stt"] = number
            number += 1


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
        self._batch_catalog = None
        self._batch_dirty = False
        self._batch_created_paths = set()
        self._registry_idle_checked = False

    @contextmanager
    def operation(self):
        # The catalog mutation gate is shared by all ProfileService instances
        # for this workspace.  Re-entering the service should not acquire the
        # same Windows byte-range lock again.
        if self._operation_depth:
            self._operation_depth += 1
            try:
                yield
            finally:
                self._operation_depth -= 1
            return
        with self.catalog_store.coordinator.mutation():
            with self.legacy_store.operation():
                self._operation_depth += 1
                self._registry_idle_checked = False
                try:
                    yield
                finally:
                    self._registry_idle_checked = False
                    self._operation_depth -= 1

    @contextmanager
    def batch_operation(self):
        """Hold one manager lock and publish one catalog for a batch.

        Filesystem work remains profile-local, but all catalog reads/writes
        performed by the nested service methods use one in-memory snapshot.
        This is intentionally a small transaction boundary for imports and
        other bounded product jobs; it does not change the normal single-item
        lifecycle methods.
        """
        if self._batch_catalog is not None:
            yield self._batch_catalog
            return
        # Keep the process-wide catalog mutation gate for the entire batch so
        # manual create/edit/delete operations cannot publish a stale snapshot
        # while the import is staging profile-local files.  The catalog write
        # lock itself is acquired only for the final commit below.
        with self.catalog_store.coordinator.mutation():
            self._operation_depth += 1
            self._registry_idle_checked = False
            try:
                self._check_registry_idle()
                catalog = self._load_catalog()
                self._batch_catalog = catalog
                self._batch_dirty = False
                self._batch_created_paths = set()
                try:
                    yield catalog
                    if self._batch_dirty:
                        self._batch_catalog = None
                        self._batch_dirty = False
                        # The legacy mirror is optional, but when enabled its
                        # short publication is still kept under its own lock.
                        with self.legacy_store.operation():
                            self._save_catalog(catalog)
                except Exception:
                    # A catalog publication failure must not make a newly-created
                    # directory look like a published profile on the next start.
                    # Preserve the directory for explicit recovery rather than
                    # deleting user data automatically.
                    for path in self._batch_created_paths:
                        if Path(path).exists():
                            self._unpublished_paths.add(Path(path).absolute())
                    raise
            finally:
                self._batch_catalog = None
                self._batch_dirty = False
                self._batch_created_paths = set()
                self._registry_idle_checked = False
                self._operation_depth -= 1

    @staticmethod
    def _empty_catalog():
        return empty_catalog()

    def _record(self, profile_id, display_name, profile_path, created_at=None, last_opened_at=None):
        record = new_profile_record(
            profile_id,
            display_name,
            profile_path,
            self.paths,
            created_at=created_at,
            last_opened_at=last_opened_at,
            clock=self.clock,
        ).to_mapping()
        record["updated_at"] = record["created_at"]
        return record

    def _touch(self, record):
        record["updated_at"] = utc_timestamp(self.clock)

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
        # Catalog reads must not initialize or repair the legacy mirror.  The
        # explicit startup schema operation performs that write when needed.
        return self.legacy_store.load() if not managed_paths and not legacy_paths else self.legacy_store._create_default()

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
        """Read and validate catalog state without any write-back."""
        if self._batch_catalog is not None:
            return self._batch_catalog
        catalog = self.catalog_store.load()
        if catalog is None:
            return self._bootstrap_catalog()
        # Existing catalogs are returned exactly as read. Migration,
        # reconciliation, and normalization belong to ensure_catalog_schema().
        return catalog

    def initialize_metadata(self):
        return self.ensure_catalog_schema()

    def ensure_catalog_schema(self):
        """Explicitly bootstrap/reconcile and publish application metadata."""
        with self.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            # Legacy reconciliation is a controlled startup/migration action;
            # status/list reads must not touch the legacy registry.
            self._reconcile_legacy_profiles(catalog)
            self._reconcile_managed_profiles(catalog)
            # Stored STT is written once per record; this only numbers records that have none yet.
            assign_missing_stt(catalog["profiles"])
            if not self.legacy_store.path.exists():
                # Preserve the legacy compatibility contract, but keep this
                # migration write at the controlled startup boundary.
                self.legacy_store.save(self.legacy_store.load())
                self._legacy_mirror_enabled = True
            self._save_catalog(catalog)
            return catalog

    def get_profile_metadata(self):
        return [dict(record) for record in self._load_catalog()["profiles"]]

    def display_position(self, profile_id):
        """Return the 1-based STT of a profile in table order, or None. The arrange rule reads this."""
        profile_id = str(profile_id)
        for position, record in table_order(self.get_profile_metadata()):
            if record.get("profile_id") == profile_id:
                return position
        return None

    def get_profile_record(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        record = self._record_map(self._load_catalog()).get(profile_id)
        if record is None:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        return dict(record)

    def get_account_metadata(self, profile_id, record=None):
        """Return the safe account association stored with one profile."""
        if record is None:
            record = self.get_profile_record(profile_id)
        account = record.get("account")
        return dict(account) if isinstance(account, dict) else None

    def set_account_metadata(self, profile_id, metadata=None):
        """Atomically set or remove one profile's safe account association."""
        profile_id = validate_profile_id(profile_id)
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ProfileManagerError("Account metadata must be an object.")
            mode = metadata.get("mode")
            allowed = (
                {"mode", "email"}
                if mode == "development"
                else {"mode", "label", "email"}
            )
            if any(not isinstance(key, str) or key not in allowed for key in metadata):
                raise ProfileManagerError(
                    "Only product account mode, label, and email identifier metadata are supported."
                )
            if mode not in {"product", "development"}:
                raise ProfileManagerError(
                    "Only product or synthetic development account metadata may be persisted."
                )
            if not isinstance(metadata.get("email"), str) or not metadata["email"].strip():
                raise ProfileManagerError("An account email identifier is required.")
            if "label" in metadata and not isinstance(metadata["label"], str):
                raise ProfileManagerError("A product account label must be text.")
            if mode == "development" and not metadata["email"].casefold().endswith(
                "@example.invalid"
            ):
                raise ProfileManagerError(
                    "Synthetic development account identifiers must end in @example.invalid."
                )
            if mode == "product" and ":" in metadata["email"]:
                raise ProfileManagerError(
                    "Product account identifiers cannot contain credential separators."
                )
            try:
                self.catalog_store._validate_field_names({"account": metadata})
            except ValueError as error:
                raise ProfileManagerError(
                    "Sensitive account metadata cannot be stored in the profile catalog."
                ) from error

        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            if metadata is None:
                record.pop("account", None)
            else:
                record["account"] = dict(metadata)
            self._touch(record)
            self._save_catalog(catalog)
        return self.get_account_metadata(profile_id)

    def get_environment(self, profile_id):
        record = self.get_profile_record(profile_id)
        preset, config = environment.effective_environment(record)
        return {"preset": preset, "environment_preset": preset, **dict(config)}

    @staticmethod
    def _normalized_proxy_settings(
        enabled, scheme=None, host=None, port=None
    ):
        """Validate one unauthenticated proxy independently of persistence."""
        if enabled is not True and enabled is not False:
            raise proxy.ProxyValidationError("Proxy state must be Enabled or Off.")
        if not enabled:
            return {"enabled": False, "scheme": None, "host": None, "port": None}
        normalized = proxy.normalize_proxy_config(scheme, host, port)
        if proxy.normalize_proxy_scheme(scheme) is None:
            raise proxy.ProxyValidationError(
                "Unsupported proxy scheme. Choose HTTP, HTTPS, SOCKS4, or SOCKS5."
            )
        if proxy.normalize_proxy_host(host) is None:
            raise proxy.ProxyValidationError(
                "Proxy host must be a hostname or IP address without a scheme, port, path, or credentials."
            )
        if proxy.normalize_proxy_port(port) is None:
            raise proxy.ProxyValidationError("Proxy port must be a number from 1 to 65535.")
        if normalized is None:
            raise proxy.ProxyValidationError("Proxy configuration is incomplete or invalid.")
        return {"enabled": True, **normalized}

    @staticmethod
    def _apply_proxy_settings(record, normalized):
        """Write an already-validated proxy state into one catalog record."""
        if not normalized["enabled"]:
            record["proxy_enabled"] = False
            for field in ("proxy_scheme", "proxy_host", "proxy_port"):
                record.pop(field, None)
            return
        record["proxy_enabled"] = True
        record.update({
            "proxy_scheme": normalized["scheme"],
            "proxy_host": normalized["host"],
            "proxy_port": normalized["port"],
        })

    @staticmethod
    def _apply_environment_settings(
        record, profile_id, preset, config=None, *, regenerate=False
    ):
        """Write an environment record while delegating policy to environment.py."""
        normalized_preset = environment.normalize_environment_preset(preset)
        materialized = environment.materialize_environment_config(
            profile_id,
            normalized_preset,
            config,
            existing_config=record.get("environment_config"),
            regenerate=regenerate,
        )
        record["environment_preset"] = normalized_preset
        record.pop("environment_config", None)
        if materialized is not None:
            record["environment_config"] = materialized
        return normalized_preset, materialized

    def set_environment(self, profile_id, preset, config=None):
        profile_id = validate_profile_id(profile_id)
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            self._apply_environment_settings(record, profile_id, preset, config)
            self._touch(record)
            self._save_catalog(catalog)
        return self.get_environment(profile_id)

    set_environment_preset = set_environment

    def get_proxy(self, profile_id):
        return dict(proxy.effective_proxy(self.get_profile_record(profile_id)))

    def set_proxy(self, profile_id, enabled, scheme=None, host=None, port=None):
        profile_id = validate_profile_id(profile_id)
        normalized = self._normalized_proxy_settings(enabled, scheme, host, port)
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            self._apply_proxy_settings(record, normalized)
            self._touch(record)
            self._save_catalog(catalog)
        return self.get_proxy(profile_id)

    def get_runtime_settings(self, profile_id):
        """Return one UI-friendly runtime view while keeping services separate."""
        record = self.get_profile_record(profile_id)
        state = environment.runtime_environment_editor_state(record)
        _, effective = environment.effective_environment(record)
        # Normal records expose persisted/effective values. Legacy Mobile is
        # intentionally presented as its R11 Android migration target, while
        # retaining its old launch behaviour until the user saves it.
        source = state if state.get("legacy_mobile_record") else effective
        environment_state = {
            "preset": state["preset"],
            "environment_preset": state["preset"],
            "user_agent": source.get("user_agent", ""),
            "language": source.get("language", ""),
            "touch_mode": bool(source.get("touch_mode", False)),
            "mobile_mode": bool(source.get("mobile_mode", False)),
            "timezone": source.get("timezone", ""),
            "window_size_policy": state.get(
                "window_size_policy", environment.WINDOW_SIZE_POLICY_SYSTEM
            ),
            "window_width": effective.get("viewport_width"),
            "window_height": effective.get("viewport_height"),
            # Retain R10 names for API consumers that used the old editor.
            "viewport_width": effective.get("viewport_width"),
            "viewport_height": effective.get("viewport_height"),
            "timezone_runtime_applied": False,
        }
        if source.get("environment_schema") != environment.PRODUCT_ENVIRONMENT_SCHEMA:
            # Legacy/refactor callers retain their historical read contract;
            # product records never expose this obsolete editable field.
            environment_state["device_scale_factor"] = source.get("device_scale_factor")
        if source.get("environment_schema") == environment.PRODUCT_ENVIRONMENT_SCHEMA:
            details = environment.product_environment_details(
                record, position=self.display_position(profile_id)
            )
            environment_state.update({
                "generated_family": details.get("generated_family"),
                "generated_revision": details.get("generated_revision"),
                "environment_seed": details.get("environment_seed"),
                "environment_signature": details.get("signature"),
                "language_order": details.get("language_order", []),
                "region": details.get("region"),
                "windows_timezone_key": details.get("windows_timezone_key"),
                "window_width": details["window_geometry"]["width"],
                "window_height": details["window_geometry"]["height"],
                "field_sources": details.get("field_sources", {}),
                "runtime_version": details.get("runtime_version"),
            })
        network = dict(proxy.effective_proxy(record))
        return {
            "environment": environment_state,
            "network": network,
            "proxy": dict(network),
        }

    @staticmethod
    def _runtime_payload(environment_preset, environment_config, proxy_config):
        """Accept both explicit arguments and one ergonomic settings mapping."""
        if not isinstance(environment_preset, dict):
            return environment_preset, environment_config, proxy_config
        payload = environment_preset
        environment_payload = payload.get("environment", payload)
        if not isinstance(environment_payload, dict):
            raise ProfileManagerError("Runtime environment settings must be an object.")
        if proxy_config is None:
            proxy_config = payload.get("network", payload.get("proxy"))
        return (
            environment_payload.get(
                "preset", environment_payload.get("environment_preset", environment.ENVIRONMENT_DESKTOP)
            ),
            environment_payload,
            proxy_config,
        )

    def save_runtime_settings(
        self, profile_id, environment_preset, environment_config=None, proxy_config=None
    ):
        """Atomically save the coherent UI payload using separate policies.

        The environment and proxy modules validate their own settings first;
        catalog persistence happens once only after both are valid.
        """
        profile_id = validate_profile_id(profile_id)
        environment_preset, environment_config, proxy_config = self._runtime_payload(
            environment_preset, environment_config, proxy_config
        )
        if proxy_config is not None and not isinstance(proxy_config, dict):
            raise proxy.ProxyValidationError("Proxy settings must be an object.")
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")

            # Validate both sides before changing the in-memory record.
            normalized_preset = environment.normalize_environment_preset(environment_preset)
            materialized = environment.materialize_environment_config(
                profile_id,
                normalized_preset,
                environment_config,
                existing_config=record.get("environment_config"),
            )
            if proxy_config is None:
                normalized_proxy = dict(proxy.effective_proxy(record))
            else:
                # Credential fields are refused, not dropped: callers must not believe authentication was saved.
                if set(proxy_config) - {"enabled", "scheme", "host", "port"}:
                    raise proxy.ProxyValidationError("Proxy settings contain an unsupported field.")
                normalized_proxy = self._normalized_proxy_settings(
                    proxy_config.get("enabled"),
                    proxy_config.get("scheme"),
                    proxy_config.get("host"),
                    proxy_config.get("port"),
                )

            record["environment_preset"] = normalized_preset
            record.pop("environment_config", None)
            if materialized is not None:
                record["environment_config"] = materialized
            self._apply_proxy_settings(record, normalized_proxy)
            self._touch(record)
            self._save_catalog(catalog)
        return self.get_runtime_settings(profile_id)

    def regenerate_environment(self, profile_id):
        """Explicitly replace a persisted Generated identity and nothing else."""
        profile_id = validate_profile_id(profile_id)
        with self.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            if environment.normalize_environment_preset(record.get("environment_preset")) != environment.ENVIRONMENT_GENERATED:
                raise ProfileManagerError("Choose Generated / Random before regenerating the environment.")
            self._apply_environment_settings(
                record,
                profile_id,
                environment.ENVIRONMENT_GENERATED,
                record.get("environment_config"),
                regenerate=True,
            )
            self._save_catalog(catalog)
        return self.get_runtime_settings(profile_id)

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
        if self._batch_catalog is catalog:
            self._batch_dirty = True
            return
        coordinator = MirrorCoordinator(
            self.catalog_store, self.legacy_store, self._legacy_mirror_enabled, self.logger
        )
        coordinator.save(catalog)
        self._legacy_mirror_enabled = coordinator.enabled

    def _check_registry_idle(self):
        if self._registry_idle_checked:
            return
        for root, label in ((self.paths.data_dir, "data"), (self.paths.profiles_dir, "managed")):
            if self.process_inspector.using_directory(root, exact=True):
                raise ProfileManagerError(f"Chromium is using the shared {label} data directory. Close it before using the manager.")
        self._registry_idle_checked = True

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

    def get_profile_dir(self, profile_id, record=None):
        profile_id = validate_profile_id(profile_id)
        if record is None:
            if self._batch_catalog is not None:
                record = self._record_map(self._batch_catalog).get(profile_id)
            else:
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

    def require_profile_dir(self, profile_id, record=None):
        profile_id = validate_profile_id(profile_id)
        if record is None:
            if self._batch_catalog is not None:
                record = self._record_map(self._batch_catalog).get(profile_id)
            else:
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
            if len(catalog["profiles"]) >= MAX_DISPLAYED_PROFILES:
                raise ProfileManagerError(
                    f"The manager supports a maximum of {MAX_DISPLAYED_PROFILES:,} profiles."
                )
            new_id = self.next_profile_id(self._record_map(catalog))
            self._initialize_profile_structure(new_id)
            profile_dir = self._resolve_profile_dir(new_id)
            new_record = self._record(new_id, display_name.strip() if display_name is not None else new_id, profile_dir)
            new_record["stt"] = next_stt(catalog["profiles"])
            catalog["profiles"].append(new_record)
            if self._batch_catalog is catalog:
                self._batch_created_paths.add(profile_dir.absolute())
            try:
                self._save_catalog(catalog)
            except Exception:
                self._unpublished_paths.add(profile_dir.absolute())
                raise
            return new_id

    @staticmethod
    def _retry_filesystem(operation, *, attempts=3, delay=0.05):
        last_error = None
        for attempt in range(attempts):
            try:
                return operation()
            except OSError as error:
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(delay * (attempt + 1))
        raise last_error

    def delete_profiles(self, profile_ids, close_callback=None):
        """Delete many stable profile IDs under one catalog operation.

        Each item is isolated from the next: a missing path, close failure, or
        transient filesystem error becomes that item's result while remaining
        IDs continue.  The catalog is published once after all staging moves.
        """
        if not isinstance(profile_ids, (list, tuple, set)):
            profile_ids = [profile_ids]
        normalized_ids = []
        seen = set()
        for value in profile_ids:
            if not value:
                continue
            profile_id = str(value)
            if profile_id.casefold() in seen:
                continue
            seen.add(profile_id.casefold())
            normalized_ids.append(profile_id)

        results = []
        pending = []
        with self.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            records = self._record_map(catalog)
            changed = False
            for profile_id in normalized_ids:
                item = {"profile_id": profile_id, "status": "failed"}
                try:
                    validate_profile_id(profile_id)
                    record = records.get(profile_id)
                    if record is None:
                        raise ProfileNotFoundError(f"Profile {profile_id} not found")
                    profile_dir = self._resolve_profile_dir(profile_id, record)
                    if self.process_inspector.using_directory(profile_dir):
                        if callable(close_callback):
                            close_callback(profile_id)
                        if self.process_inspector.using_directory(profile_dir):
                            raise ProfileManagerError(
                                f"Close Chromium for {profile_id} before deleting it."
                            )
                    staged = None
                    if profile_dir.exists():
                        if not profile_dir.is_dir():
                            raise ProfileManagerError(
                                f"Profile path is not a directory: {profile_dir}"
                            )
                        staged = checked_path(
                            profile_dir.parent / f".deleting-{profile_id}-{uuid.uuid4().hex}",
                            profile_dir.parent,
                        )
                        self._retry_filesystem(lambda: profile_dir.rename(staged))
                    else:
                        self._check_pending_delete(profile_id, profile_dir.parent)
                    catalog["profiles"] = [
                        value for value in catalog["profiles"]
                        if value["profile_id"] != profile_id
                    ]
                    records.pop(profile_id, None)
                    changed = True
                    pending.append((profile_id, staged))
                    item["status"] = "deleted"
                    item["error"] = None
                except Exception as error:
                    item["error"] = str(error)[:240] or error.__class__.__name__
                results.append(item)

            if changed:
                compact_stt(catalog["profiles"])
                self._save_catalog(catalog)
                for profile_id, staged in pending:
                    if staged is None:
                        continue
                    try:
                        checked_path(staged, staged.parent)
                        self._retry_filesystem(lambda path=staged: shutil.rmtree(path))
                    except OSError as error:
                        # Metadata is already published, so retain an explicit
                        # failure result and leave the staging directory for
                        # manual recovery rather than retrying indefinitely.
                        for item in results:
                            if item["profile_id"] == profile_id:
                                item["status"] = "failed"
                                item["error"] = (
                                    f"Profile metadata was removed, but profile data could not "
                                    f"be cleaned up: {error}"
                                )[:240]
                                break

        deleted = sum(item["status"] == "deleted" for item in results)
        failed = len(results) - deleted
        return {
            "results": results,
            "requested": len(normalized_ids),
            "deleted": deleted,
            "failed": failed,
        }

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
            # STT is stored separately, so a rename changes the label and never the row's place.
            record["display_name"] = new_name.strip()
            self._touch(record)
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
            compact_stt(catalog["profiles"])
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
            if len(catalog["profiles"]) >= MAX_DISPLAYED_PROFILES:
                raise ProfileManagerError(
                    f"The manager supports a maximum of {MAX_DISPLAYED_PROFILES:,} profiles."
                )
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
            self._touch(record)
            self._save_catalog(catalog)
            return
        with self.operation():
            self._check_registry_idle()
            catalog = catalog or self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record["last_opened_at"] = utc_timestamp(self.clock)
            self._touch(record)
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
