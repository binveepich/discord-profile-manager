"""Application catalog and legacy compatibility storage boundaries."""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import tempfile
from pathlib import PureWindowsPath

from .core import (
    MANAGER_PATH_KEY,
    NEW_PROFILE_PATTERN,
    ProfileManagerError,
    checked_path,
    metadata_path_for_profile,
    profile_path_from_metadata,
    validate_manager_path,
    validate_profile_id,
)


METADATA_VERSION = 1


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


def _logger_or_null(logger):
    return logger if logger is not None else _NullLogger()


class OperationLock:
    """Small cross-process non-blocking lock for manager mutations."""

    def __init__(self, path, root, logger=None):
        self.path = checked_path(Path(path), root)
        self.root = Path(root).absolute()
        self.logger = _logger_or_null(logger)

    @contextmanager
    def acquire(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = None
        try:
            lock = open(self.path, "a+b")
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            try:
                acquire()
            except OSError as error:
                raise ProfileManagerError(
                    "Another profile operation is in progress. Please retry."
                ) from error
            try:
                yield
            finally:
                try:
                    lock.seek(0)
                    release()
                except OSError:
                    self.logger.warning("Could not release the manager operation lock")
        finally:
            if lock is not None:
                lock.close()


class LegacyStateStore:
    """Read/write the legacy Chromium-shaped manager registry."""

    def __init__(self, paths, logger=None):
        self.paths = paths
        self.path = paths.local_state
        self._loaded_bytes = None
        self.logger = _logger_or_null(logger)
        self.lock = OperationLock(paths.data_dir / ".manager.lock", paths.data_dir, logger)

    @contextmanager
    def operation(self):
        with self.lock.acquire():
            yield

    @staticmethod
    def _unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate metadata key")
            result[key] = value
        return result

    def _validate(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("profile"), dict):
            raise ValueError("Expected a profile object")
        cache = data["profile"].get("info_cache")
        if not isinstance(cache, dict):
            raise ValueError("Expected profile.info_cache object")
        seen = set()
        seen_manager_paths = set()
        for profile_id, info in cache.items():
            validate_profile_id(profile_id)
            if profile_id.casefold() in seen:
                raise ValueError("Profile IDs refer to the same Windows directory")
            seen.add(profile_id.casefold())
            if not isinstance(info, dict) or not isinstance(info.get("name", profile_id), str):
                raise ValueError("Invalid profile entry or name")
            manager_path = info.get(MANAGER_PATH_KEY)
            if manager_path is not None:
                validate_manager_path(manager_path)
                folded = manager_path.casefold()
                if folded in seen_manager_paths:
                    raise ValueError("Managed profile paths refer to the same Windows directory")
                seen_manager_paths.add(folded)
            created = info.get("created", 0)
            if (
                isinstance(created, bool)
                or not isinstance(created, (int, float))
                or created < 0
                or created > 2**63 - 1
                or not math.isfinite(created)
            ):
                raise ValueError("Invalid profile creation timestamp")
        return data

    def _empty_data_exists(self):
        existing = []
        if self.paths.data_dir.is_dir():
            existing.extend(
                path for path in self.paths.data_dir.iterdir()
                if path.name != ".manager.lock"
            )
        if self.paths.profiles_dir.is_dir():
            existing.extend(
                path for path in self.paths.profiles_dir.iterdir()
                if path.name != ".manager.lock"
            )
        return existing

    def load(self):
        """Load without repairing malformed or unexpectedly missing state."""
        try:
            checked_path(self.path, self.paths.data_dir)
            if not self.path.exists():
                if self._empty_data_exists():
                    raise ProfileManagerError(
                        "Profile metadata is missing, but existing profile data remains. "
                        "Restore the legacy state before continuing."
                    )
                self._loaded_bytes = None
                return self._create_default()
            raw = self.path.read_bytes()
            data = self._validate(json.loads(
                raw.decode("utf-8-sig"), object_pairs_hook=self._unique_keys
            ))
            self._loaded_bytes = raw
            return data
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            raise ProfileManagerError(
                "Cannot read legacy profile metadata. The file was left unchanged."
            ) from error

    def save(self, data):
        """Validate and atomically replace the legacy registry."""
        temp_path = None
        try:
            self._validate(data)
            checked_path(self.path, self.paths.data_dir)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self._loaded_bytes:
                raise ProfileManagerError(
                    "Profile metadata changed during this operation. Refresh and retry."
                )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".local-state-", suffix=".tmp", delete=False
            ) as stream:
                temp_path = Path(stream.name)
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            new_bytes = temp_path.read_bytes()
            temp_path.replace(self.path)
            self._loaded_bytes = new_bytes
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            self.logger.error("Failed to save legacy profile metadata")
            raise ProfileManagerError("Cannot save legacy profile metadata.") from error
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    self.logger.warning("Could not remove a temporary legacy metadata file")

    @staticmethod
    def _create_default():
        return {"profile": {"info_cache": {}}}


class ProfileCatalogStore:
    """Application-owned versioned catalog with atomic optimistic writes."""

    _forbidden_fragments = (
        "password", "token", "totp", "cookie", "session", "proxycredential", "extensionsecret"
    )
    required_fields = {
        "profile_id", "display_name", "profile_directory", "created_at",
        "last_opened_at", "proxy_enabled",
    }

    def __init__(self, paths, logger=None):
        self.paths = paths
        self.path = paths.profiles_json
        self._loaded_bytes = None
        self.logger = _logger_or_null(logger)

    @classmethod
    def _validate_field_names(cls, value):
        if isinstance(value, dict):
            for field, nested in value.items():
                normalized = str(field).replace("_", "").replace("-", "").casefold()
                if any(fragment in normalized for fragment in cls._forbidden_fragments):
                    raise ValueError(f"Sensitive field is not allowed in profiles.json: {field}")
                cls._validate_field_names(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._validate_field_names(nested)

    @staticmethod
    def _validate_timestamp(value, required=False):
        if value is None and not required:
            return
        if not isinstance(value, str) or not value:
            raise ValueError("Invalid application metadata timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid application metadata timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError("Application metadata timestamps must include a timezone")

    @classmethod
    def _validate(cls, data, paths):
        if not isinstance(data, dict):
            raise ValueError("Expected an application metadata object")
        cls._validate_field_names(data)
        if isinstance(data.get("version"), bool) or data.get("version") != METADATA_VERSION:
            raise ValueError("Unsupported application metadata version")
        records = data.get("profiles")
        if not isinstance(records, list):
            raise ValueError("Expected a profiles list")
        seen_ids = set()
        seen_directories = set()
        for record in records:
            if not isinstance(record, dict) or not cls.required_fields.issubset(record):
                raise ValueError("Incomplete profile metadata record")
            profile_id = validate_profile_id(record["profile_id"])
            folded_id = profile_id.casefold()
            if folded_id in seen_ids:
                raise ValueError("Duplicate profile IDs in profiles.json")
            seen_ids.add(folded_id)
            if not isinstance(record["display_name"], str) or not record["display_name"].strip():
                raise ValueError("Invalid profile display name")
            profile_path = profile_path_from_metadata(record["profile_directory"], paths)
            directory_key = metadata_path_for_profile(profile_path, paths).casefold()
            if directory_key in seen_directories:
                raise ValueError("Duplicate profile directory mappings in profiles.json")
            seen_directories.add(directory_key)
            cls._validate_timestamp(record["created_at"], required=True)
            cls._validate_timestamp(record["last_opened_at"])
        return data

    @staticmethod
    def _unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate metadata key")
            result[key] = value
        return result

    def load(self):
        """Load the catalog; missing/empty is uninitialized, invalid is preserved."""
        try:
            if not self.path.exists():
                self._loaded_bytes = None
                return None
            raw = self.path.read_bytes()
            if not raw.strip():
                self._loaded_bytes = raw
                return None
            data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=self._unique_keys)
            self._validate(data, self.paths)
            self._loaded_bytes = raw
            return data
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            raise ProfileManagerError(
                "Cannot read application profile metadata. The file was left unchanged."
            ) from error

    def save(self, data):
        """Validate, revalidate, fsync, and atomically publish the catalog."""
        temp_path = None
        try:
            self._validate(data, self.paths)
            parent = self.path.parent
            checked_path(parent, self.paths.root)
            parent.mkdir(parents=True, exist_ok=True)
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self._loaded_bytes:
                raise ProfileManagerError(
                    "Application profile metadata changed during this operation. Refresh and retry."
                )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=parent,
                prefix=".profiles-", suffix=".tmp", delete=False
            ) as stream:
                temp_path = Path(stream.name)
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            candidate_bytes = temp_path.read_bytes()
            candidate = json.loads(
                candidate_bytes.decode("utf-8"), object_pairs_hook=self._unique_keys
            )
            self._validate(candidate, self.paths)
            temp_path.replace(self.path)
            self._loaded_bytes = candidate_bytes
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            self.logger.error("Failed to save application profile metadata")
            raise ProfileManagerError(
                "Cannot save application profile metadata."
            ) from error
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    self.logger.warning("Could not remove a temporary profiles.json file")


class ExtensionPolicyStore:
    """Persist the global extension enablement policy outside the registry.

    The repository ``extensions/`` tree is a read-only source registry from
    the manager's point of view.  Only extension names are stored here; source
    paths and manifests are rediscovered at runtime.
    """

    version = 1

    def __init__(self, paths, logger=None):
        self.paths = paths
        self.path = paths.extension_policy_json
        self._loaded_bytes = None
        self.logger = _logger_or_null(logger)

    @staticmethod
    def _unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate extension policy key")
            result[key] = value
        return result

    @staticmethod
    def _valid_extension_name(value):
        if not isinstance(value, str) or not value or value != value.strip():
            return False
        windows_path = PureWindowsPath(value.replace("/", "\\"))
        return not (
            windows_path.is_absolute()
            or windows_path.drive
            or len(windows_path.parts) != 1
            or windows_path.parts[0] in ("", ".", "..")
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in value)
        )

    @classmethod
    def _validate(cls, data):
        if not isinstance(data, dict) or data.get("version") != cls.version:
            raise ValueError("Unsupported extension policy version")
        enabled = data.get("enabled_extensions")
        if not isinstance(enabled, list):
            raise ValueError("Expected an enabled_extensions list")
        seen = set()
        for name in enabled:
            if not cls._valid_extension_name(name):
                raise ValueError("Invalid extension name in global policy")
            folded = name.casefold()
            if folded in seen:
                raise ValueError("Duplicate extension in global policy")
            seen.add(folded)
        return data

    @staticmethod
    def empty_policy():
        return {"version": ExtensionPolicyStore.version, "enabled_extensions": []}

    def load(self):
        """Load policy, falling back safely when it is missing or malformed."""
        try:
            if not self.path.exists():
                self._loaded_bytes = None
                return self.empty_policy()
            raw = self.path.read_bytes()
            if not raw.strip():
                self._loaded_bytes = raw
                return self.empty_policy()
            data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=self._unique_keys)
            self._validate(data)
            self._loaded_bytes = raw
            return data
        except (OSError, ValueError, UnicodeError) as error:
            # A broken optional policy must not prevent the manager from
            # opening profiles.  Required built-ins are enforced by the
            # extension service, and a later user save can repair this file.
            self._loaded_bytes = raw if "raw" in locals() else None
            self.logger.warning(
                "Global extension policy is unreadable; using required built-ins only"
            )
            return self.empty_policy()

    def save(self, data):
        """Validate and atomically publish the application-owned policy."""
        temp_path = None
        try:
            self._validate(data)
            parent = self.path.parent
            checked_path(parent, self.paths.root)
            parent.mkdir(parents=True, exist_ok=True)
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self._loaded_bytes:
                raise ProfileManagerError(
                    "Global extension policy changed during this operation. Refresh and retry."
                )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=parent,
                prefix=".extensions-", suffix=".tmp", delete=False
            ) as stream:
                temp_path = Path(stream.name)
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            candidate_bytes = temp_path.read_bytes()
            candidate = json.loads(
                candidate_bytes.decode("utf-8"), object_pairs_hook=self._unique_keys
            )
            self._validate(candidate)
            temp_path.replace(self.path)
            self._loaded_bytes = candidate_bytes
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            self.logger.error("Failed to save global extension policy")
            raise ProfileManagerError("Cannot save global extension policy.") from error
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    self.logger.warning("Could not remove a temporary extension policy file")


class MirrorCoordinator:
    """Publish the optional legacy mirror with compensating restore."""

    def __init__(self, catalog_store, legacy_store, enabled=False, logger=None):
        self.catalog_store = catalog_store
        self.legacy_store = legacy_store
        self.enabled = enabled
        self.logger = _logger_or_null(logger)

    def _legacy_info_for_record(self, record, existing=None):
        info = dict(existing or {})
        info["name"] = record["display_name"]
        try:
            info["created"] = int(
                datetime.fromisoformat(record["created_at"].replace("Z", "+00:00")).timestamp()
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            info["created"] = 0
        path = profile_path_from_metadata(record["profile_directory"], self.catalog_store.paths)
        if path.absolute().is_relative_to(self.catalog_store.paths.profiles_dir.absolute()):
            info[MANAGER_PATH_KEY] = path.name
        else:
            info.pop(MANAGER_PATH_KEY, None)
        return info

    def _sync_legacy(self, catalog):
        if not self.enabled:
            return None
        try:
            state = self.legacy_store.load()
        except ProfileManagerError:
            self.logger.warning("Skipping unreadable legacy compatibility mirror")
            self.enabled = False
            return None
        existing = {
            profile_id: dict(info)
            for profile_id, info in state["profile"]["info_cache"].items()
        }
        state["profile"]["info_cache"] = {
            record["profile_id"]: self._legacy_info_for_record(
                record, existing.get(record["profile_id"])
            )
            for record in catalog["profiles"]
        }
        self.legacy_store.save(state)
        return state

    def _restore_legacy(self, original_bytes):
        path = self.legacy_store.path
        if original_bytes is None:
            if path.exists():
                path.unlink()
            self.legacy_store._loaded_bytes = None
            return
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=parent, prefix=".local-state-rollback-",
                suffix=".tmp", delete=False
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(original_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(path)
            self.legacy_store._loaded_bytes = original_bytes
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def save(self, catalog):
        """Publish mirror then catalog, restoring mirror if catalog fails."""
        original_legacy = None
        attempted = False
        try:
            if self.enabled:
                original_legacy = self.legacy_store.path.read_bytes() if self.legacy_store.path.exists() else None
                attempted = True
                self._sync_legacy(catalog)
            self.catalog_store.save(catalog)
        except Exception:
            if attempted:
                try:
                    self._restore_legacy(original_legacy)
                except OSError:
                    self.logger.error("Could not restore the legacy compatibility mirror")
            raise


def empty_catalog():
    return {"version": METADATA_VERSION, "profiles": []}
