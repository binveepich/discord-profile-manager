#!/usr/bin/env python3
"""
Ungoogled Chromium Profile Manager
Launches the bundled browser/chrome.exe runtime directly
Supports multiple Discord accounts with auto-fill extension
"""

import os
import json
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk, filedialog
from pathlib import Path
import time
import re
import shutil
import logging
from datetime import datetime, timezone
import signal
import psutil
import math
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import PureWindowsPath

# ----------------------------------------------------------------------
# Configuration and Paths
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
BROWSER_EXE = PROJECT_ROOT / "browser" / "chrome.exe"
# The application catalog is separate from Chromium's per-profile Local State.
CONFIG_DIR = PROJECT_ROOT / "config"
PROFILES_JSON = CONFIG_DIR / "profiles.json"
# Keep the existing legacy registry for compatibility with M1-M3 installations.
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = PROJECT_ROOT / "profiles"
LOG_DIR = BASE_DIR / "log"
EXTENSIONS_DIR = PROJECT_ROOT / "extensions"
AUTOFILL_EXTENSION_NAME = "discord-autofill-extension"
EXT_DIR = EXTENSIONS_DIR / AUTOFILL_EXTENSION_NAME
PROFILE_EXTENSIONS_DIR_NAME = "Unpacked Extensions"
LOCAL_STATE = DATA_DIR / "Local State"

NEW_PROFILE_PATTERN = re.compile(r"^profile_(\d+)$", re.IGNORECASE)
MANAGER_PATH_KEY = "manager_path"
METADATA_VERSION = 1
DEFAULT_ENVIRONMENT_PRESET = "default"
PROFILE_TABLE_COLUMNS = (
    "name", "account", "environment", "proxy", "status", "last_opened"
)
PROFILE_TABLE_DATA_COLUMNS = PROFILE_TABLE_COLUMNS + ("id",)

# Ensure log directory exists
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Setup logging
log_file = LOG_DIR / f"profile_manager_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('ProfileManager')

# ----------------------------------------------------------------------
# Exception Classes
# ----------------------------------------------------------------------
class ProfileManagerError(Exception):
    """Base exception for profile manager errors"""
    pass

class ProfileNotFoundError(ProfileManagerError):
    """Profile not found in Local State"""
    pass

class ExtensionError(ProfileManagerError):
    """Base error for extension discovery and deployment."""
    pass

class ExtensionNotFoundError(ExtensionError):
    """Discord autofill extension source is not available."""
    pass

class ExtensionDeploymentError(ExtensionError):
    """A profile extension deployment could not be completed safely."""
    pass

class InvalidAccountFormatError(ProfileManagerError):
    """Invalid account format for Discord credentials"""
    pass


def validate_profile_id(profile_id):
    """Reject Windows path aliases and paths that could address another profile."""
    if (not isinstance(profile_id, str) or not profile_id
            or profile_id != profile_id.strip() or profile_id.endswith('.')
            or profile_id in ('.', '..') or profile_id.startswith('.deleting-')
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in profile_id)
            or PureWindowsPath(profile_id).is_reserved()):
        raise ProfileManagerError("Invalid profile ID in metadata. Restore or correct Local State before continuing.")
    return profile_id


def checked_path(path, root):
    """Require containment and reject symlinks/junctions along the managed path."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root):
        raise ProfileManagerError("Profile path is outside its data directory.")
    for item in [root, *[root.joinpath(*path.relative_to(root).parts[:i])
                         for i in range(1, len(path.relative_to(root).parts) + 1)]]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        reparse_point = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        if stat.S_ISLNK(info.st_mode) or reparse_point and getattr(info, 'st_file_attributes', 0) & reparse_point:
            raise ProfileManagerError(f"Linked profile paths are not supported: {item}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ProfileManagerError("Profile path resolves outside its data directory.")
    return path


def validate_manager_path(manager_path):
    """Validate the managed profile directory name stored in Local State."""
    if not isinstance(manager_path, str) or not NEW_PROFILE_PATTERN.fullmatch(manager_path):
        raise ProfileManagerError("Invalid managed profile path in metadata. Restore or correct Local State before continuing.")
    return manager_path


def validate_candidate_profile_name(profile_name):
    """Return whether a directory name can safely become a profile ID."""
    try:
        validate_profile_id(profile_name)
    except ProfileManagerError:
        return False
    return True


def ensure_tree_has_no_links(root):
    """Reject links/reparse points anywhere before copying a profile tree."""
    root = checked_path(root, root.parent)
    reparse_point = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            item = Path(current) / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or reparse_point and getattr(info, 'st_file_attributes', 0) & reparse_point:
                raise ProfileManagerError(f"Linked profile data cannot be migrated: {item}")


def browser_using_directory(directory, exact=False):
    """Check live processes, including browsers started before this manager."""
    directory = Path(directory).resolve()
    try:
        for process in psutil.process_iter(['name']):
            if (process.info.get('name') or '').lower() not in ('chrome.exe', 'chromium.exe', 'chrome', 'chromium'):
                continue
            try:
                owner = process
                # Sandboxed renderers can deny cmdline access on Windows. Their
                # browser parent still identifies the user-data root reliably.
                for _ in range(10):
                    try:
                        args = owner.cmdline()
                        break
                    except psutil.AccessDenied:
                        owner = owner.parent()
                        if owner is None or owner.name().lower() not in ('chrome.exe', 'chromium.exe', 'chrome', 'chromium'):
                            raise
                else:
                    raise ProfileManagerError("Cannot identify a Chromium process's profile. Close Chromium and retry.")
                for index, argument in enumerate(args):
                    value = None
                    if argument.startswith('--user-data-dir='):
                        value = argument.split('=', 1)[1]
                    elif argument == '--user-data-dir' and index + 1 < len(args):
                        value = args[index + 1]
                    if value:
                        candidate = Path(value.strip('"'))
                        if not candidate.is_absolute():
                            candidate = Path(owner.cwd()) / candidate
                        candidate = candidate.resolve()
                        if candidate == directory or (not exact and (
                                directory.is_relative_to(candidate) or candidate.is_relative_to(directory))):
                            return True
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                raise ProfileManagerError("Cannot verify whether Chromium is using this profile. Close Chromium and retry.")
    except (psutil.Error, OSError) as error:
        raise ProfileManagerError("Cannot check running Chromium processes. Retry after closing Chromium.") from error
    return False

# ----------------------------------------------------------------------
# Local State Management
# ----------------------------------------------------------------------
class LocalStateManager:
    """Manage Chromium Local State file operations"""
    
    def __init__(self):
        self.local_state_path = LOCAL_STATE
        self._loaded_bytes = None

    @contextmanager
    def operation(self):
        """Serialize manager mutations/launches across application instances."""
        directory = checked_path(self.local_state_path.parent, DATA_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = checked_path(directory / '.manager.lock', directory)
        with open(lock_path, 'a+b') as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            if sys.platform == 'win32':
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
                raise ProfileManagerError("Another profile operation is in progress. Please retry.") from error
            try:
                yield
            finally:
                lock.seek(0)
                release()

    def _validate(self, data):
        if not isinstance(data, dict) or not isinstance(data.get('profile'), dict):
            raise ValueError('Expected a profile object')
        cache = data['profile'].get('info_cache')
        if not isinstance(cache, dict):
            raise ValueError('Expected profile.info_cache object')
        seen = set()
        seen_manager_paths = set()
        for pid, info in cache.items():
            validate_profile_id(pid)
            if pid.casefold() in seen:
                raise ValueError('Profile IDs refer to the same Windows directory')
            seen.add(pid.casefold())
            if not isinstance(info, dict) or not isinstance(info.get('name', pid), str):
                raise ValueError('Invalid profile entry or name')
            manager_path = info.get(MANAGER_PATH_KEY)
            if manager_path is not None:
                validate_manager_path(manager_path)
                folded_manager_path = manager_path.casefold()
                if folded_manager_path in seen_manager_paths:
                    raise ValueError('Managed profile paths refer to the same Windows directory')
                seen_manager_paths.add(folded_manager_path)
            created = info.get('created', 0)
            if (isinstance(created, bool) or not isinstance(created, (int, float))
                    or created < 0 or created > 2**63 - 1 or not math.isfinite(created)):
                raise ValueError('Invalid profile creation timestamp')
        return data

    @staticmethod
    def _unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate metadata key')
            result[key] = value
        return result
        
    def load(self):
        """Read metadata without replacing unreadable or malformed existing data."""
        try:
            checked_path(self.local_state_path, DATA_DIR)
            if not self.local_state_path.exists():
                directory = self.local_state_path.parent
                existing = [path for path in directory.iterdir()
                            if path.name != '.manager.lock'] if directory.exists() else []
                profiles_root = Path(PROFILES_DIR)
                checked_path(profiles_root, PROJECT_ROOT)
                if profiles_root.exists():
                    existing.extend(path for path in profiles_root.iterdir()
                                    if path.name != '.manager.lock')
                if existing:
                    raise ProfileManagerError(
                        f"Profile metadata is missing, but existing profile data remains at {directory} or {profiles_root}. "
                        "Restore Local State before continuing."
                    )
                self._loaded_bytes = None
                return self._create_default()
            raw = self.local_state_path.read_bytes()
            data = self._validate(json.loads(raw.decode('utf-8-sig'), object_pairs_hook=self._unique_keys))
            self._loaded_bytes = raw
            return data
        except (OSError, ValueError, UnicodeError) as error:
            raise ProfileManagerError(
                f"Cannot read profile metadata: {self.local_state_path}. The file was left unchanged; restore or correct it before continuing."
            ) from error
    
    def save(self, data):
        """Safely write Local State JSON file"""
        temp_path = None
        try:
            self._validate(data)
            checked_path(self.local_state_path, DATA_DIR)
            self.local_state_path.parent.mkdir(parents=True, exist_ok=True)
            current = self.local_state_path.read_bytes() if self.local_state_path.exists() else None
            if current != self._loaded_bytes:
                raise ProfileManagerError("Profile metadata changed during this operation. Refresh and retry.")
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.local_state_path.parent,
                                             prefix='.local-state-', suffix='.tmp', delete=False) as f:
                temp_path = Path(f.name)
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            new_bytes = temp_path.read_bytes()
            temp_path.replace(self.local_state_path)
            self._loaded_bytes = new_bytes
            logger.debug("Local State saved successfully")
        except Exception as e:
            logger.error(f"Failed to save Local State: {e}")
            raise ProfileManagerError(f"Cannot save Local State: {e}")
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    logger.warning("Could not remove a temporary metadata file")
    
    def _create_default(self):
        """Create default Local State structure"""
        return {
            "profile": {
                "info_cache": {}
            }
        }


# ----------------------------------------------------------------------
# Application Profile Metadata
# ----------------------------------------------------------------------
def utc_timestamp():
    """Return a stable, timezone-aware timestamp for application metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def timestamp_from_epoch(value):
    """Convert legacy Chromium-style seconds to the M4 timestamp format."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or not math.isfinite(value):
        return utc_timestamp()
    try:
        return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    except (OverflowError, OSError, ValueError):
        return utc_timestamp()


def metadata_path_for_profile(path):
    """Serialize a profile path relative to one of the two allowed profile roots."""
    path = Path(path).absolute()
    for root, prefix in ((PROFILES_DIR, ('profiles',)), (DATA_DIR, ('legacy', 'data'))):
        root = Path(root).absolute()
        if path.is_relative_to(root):
            relative = path.relative_to(root)
            if not relative.parts:
                raise ProfileManagerError("A profile directory must be below its profile root.")
            return '/'.join((*prefix, *relative.parts))
    raise ProfileManagerError("Profile directory is outside the managed profile roots.")


def profile_path_from_metadata(value):
    """Resolve and validate a serialized profile path without accepting traversal."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProfileManagerError("Invalid profile_directory in application metadata.")
    windows_path = PureWindowsPath(value.replace('/', '\\'))
    if windows_path.is_absolute() or windows_path.drive or any(part in ('', '.', '..') for part in windows_path.parts):
        raise ProfileManagerError("Invalid profile_directory in application metadata.")
    parts = windows_path.parts
    folded_parts = tuple(part.casefold() for part in parts)
    if folded_parts[:1] == ('profiles',) and len(parts) > 1:
        root, relative_parts = Path(PROFILES_DIR), parts[1:]
    elif folded_parts[:2] == ('legacy', 'data') and len(parts) > 2:
        root, relative_parts = Path(DATA_DIR), parts[2:]
    else:
        raise ProfileManagerError("Profile directory must be under profiles/ or legacy/data/.")
    candidate = root.joinpath(*relative_parts)
    return checked_path(candidate, root)


class ProfileMetadataManager:
    """Read and atomically write application-owned profile metadata."""

    _forbidden_fragments = (
        'password', 'token', 'totp', 'cookie', 'session', 'proxycredential', 'extensionsecret'
    )

    def __init__(self):
        self.path = PROFILES_JSON
        self._loaded_bytes = None

    @classmethod
    def _validate_field_names(cls, value):
        if isinstance(value, dict):
            for field, nested in value.items():
                normalized = str(field).replace('_', '').replace('-', '').casefold()
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
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise ValueError("Invalid application metadata timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError("Application metadata timestamps must include a timezone")

    @classmethod
    def _validate(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Expected an application metadata object")
        cls._validate_field_names(data)
        version = data.get('version')
        if isinstance(version, bool) or version != METADATA_VERSION:
            raise ValueError("Unsupported application metadata version")
        records = data.get('profiles')
        if not isinstance(records, list):
            raise ValueError("Expected a profiles list")

        seen_ids = set()
        seen_directories = set()
        required = {
            'profile_id', 'display_name', 'profile_directory', 'created_at',
            'last_opened_at', 'environment_preset', 'proxy_enabled'
        }
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid profile metadata record")
            if not required.issubset(record):
                raise ValueError("Incomplete profile metadata record")
            profile_id = validate_profile_id(record['profile_id'])
            folded_id = profile_id.casefold()
            if folded_id in seen_ids:
                raise ValueError("Duplicate profile IDs in profiles.json")
            seen_ids.add(folded_id)
            if not isinstance(record['display_name'], str) or not record['display_name'].strip():
                raise ValueError("Invalid profile display name")
            profile_path = profile_path_from_metadata(record['profile_directory'])
            directory_key = metadata_path_for_profile(profile_path).casefold()
            if directory_key in seen_directories:
                raise ValueError("Duplicate profile directory mappings in profiles.json")
            seen_directories.add(directory_key)
            cls._validate_timestamp(record['created_at'], required=True)
            cls._validate_timestamp(record['last_opened_at'])
            if not isinstance(record['environment_preset'], str) or not record['environment_preset'].strip():
                raise ValueError("Invalid environment preset")
            if not isinstance(record['proxy_enabled'], bool):
                raise ValueError("Invalid proxy_enabled value")
        return data

    @staticmethod
    def _unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate metadata key')
            result[key] = value
        return result

    def load(self):
        """Load the catalog; missing or zero-byte metadata is treated as uninitialized."""
        try:
            if not self.path.exists():
                self._loaded_bytes = None
                return None
            raw = self.path.read_bytes()
            self._loaded_bytes = raw
            if not raw.strip():
                return None
            data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=self._unique_keys)
            return self._validate(data)
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            raise ProfileManagerError(
                f"Cannot read application profile metadata: {self.path}. The file was left unchanged."
            ) from error

    def save(self, data):
        """Validate and atomically replace profiles.json."""
        temp_path = None
        try:
            self._validate(data)
            parent = self.path.parent
            parent.mkdir(parents=True, exist_ok=True)
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self._loaded_bytes:
                raise ProfileManagerError("Application profile metadata changed during this operation. Refresh and retry.")
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=parent,
                                             prefix='.profiles-', suffix='.tmp', delete=False) as temp:
                temp_path = Path(temp.name)
                json.dump(data, temp, indent=2, ensure_ascii=False)
                temp.write('\n')
                temp.flush()
                os.fsync(temp.fileno())
            candidate_bytes = temp_path.read_bytes()
            candidate = json.loads(candidate_bytes.decode('utf-8'), object_pairs_hook=self._unique_keys)
            self._validate(candidate)
            temp_path.replace(self.path)
            self._loaded_bytes = candidate_bytes
        except ProfileManagerError:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            raise ProfileManagerError(f"Cannot save application profile metadata: {self.path}.") from error
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    logger.warning("Could not remove a temporary profiles.json file")

# ----------------------------------------------------------------------
# Profile Management
# ----------------------------------------------------------------------
class ProfileManager:
    """Handle profile operations"""
    
    def __init__(self):
        self.local_state = LocalStateManager()
        self.metadata = ProfileMetadataManager()
        # Existing installations may still have integrations that inspect the
        # legacy registry. Keep it synchronized when it exists, but never use
        # it as the primary catalog after profiles.json is initialized.
        self._legacy_mirror_enabled = LOCAL_STATE.exists()
        self._unpublished_paths = set()

    @staticmethod
    def _empty_catalog():
        return {'version': METADATA_VERSION, 'profiles': []}

    @staticmethod
    def _record(profile_id, display_name, profile_path, created_at=None, last_opened_at=None):
        return {
            'profile_id': profile_id,
            'display_name': display_name,
            'profile_directory': metadata_path_for_profile(profile_path),
            'created_at': created_at or utc_timestamp(),
            'last_opened_at': last_opened_at,
            'environment_preset': DEFAULT_ENVIRONMENT_PRESET,
            'proxy_enabled': False,
        }

    @staticmethod
    def _record_map(data):
        return {record['profile_id']: record for record in data['profiles']}

    def _legacy_record(self, profile_id, info):
        if not isinstance(info, dict):
            raise ProfileManagerError(f"Invalid legacy profile metadata for {profile_id}.")
        manager_path = info.get(MANAGER_PATH_KEY)
        if manager_path is not None:
            manager_path = validate_manager_path(manager_path)
            profile_path = checked_path(PROFILES_DIR / manager_path, PROFILES_DIR)
        else:
            profile_path = checked_path(DATA_DIR / profile_id, DATA_DIR)
        display_name = info.get('name', profile_id)
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = profile_id
        return self._record(
            profile_id,
            display_name,
            profile_path,
            created_at=timestamp_from_epoch(info.get('created', 0)),
            last_opened_at=info.get('last_opened_at') if isinstance(info.get('last_opened_at'), str) else None,
        )

    @staticmethod
    def _looks_like_profile_directory(path):
        return path.is_dir() and (
            (path / 'Default' / 'Preferences').is_file()
            or (path / 'Preferences').is_file()
        )

    def _scan_profile_root(self, root):
        """Find valid-looking profile roots without touching their contents."""
        found = []
        root = Path(root)
        if not root.is_dir():
            return found
        for path in root.iterdir():
            if path.name in ('.manager.lock', 'Local State') or path.name.startswith('.'):
                continue
            if (Path(root).absolute() == Path(PROFILES_DIR).absolute()
                    and not NEW_PROFILE_PATTERN.fullmatch(path.name)):
                continue
            if not validate_candidate_profile_name(path.name):
                continue
            try:
                checked_path(path, root)
            except ProfileManagerError:
                continue
            if self._looks_like_profile_directory(path):
                if path.absolute() not in self._unpublished_paths:
                    found.append(path)
        return found

    def _read_legacy_catalog_for_bootstrap(self, managed_paths, legacy_paths):
        """Read the old registry only when profiles.json has not been initialized."""
        if LOCAL_STATE.exists():
            try:
                return self.local_state.load()
            except ProfileManagerError:
                # A valid managed/legacy profile can still be recovered without
                # trusting a damaged pre-M4 registry. If there is no physical
                # profile to recover, retain the M1-M3 safety error unchanged.
                if not managed_paths and not legacy_paths:
                    raise
                logger.warning("Legacy Local State could not be read; recovering physical profiles into profiles.json")
                return self.local_state._create_default()

        if not managed_paths and not legacy_paths:
            # Preserve M1-M3 behavior for unrelated legacy files/directories.
            state = self.local_state.load()
        else:
            state = self.local_state._create_default()
        # Keep a compatibility registry available for old integrations. This
        # file is not used as the application catalog after this bootstrap.
        self.local_state.save(state)
        return state

    def _bootstrap_catalog(self):
        managed_paths = self._scan_profile_root(PROFILES_DIR)
        legacy_paths = self._scan_profile_root(DATA_DIR)
        legacy_state = self._read_legacy_catalog_for_bootstrap(managed_paths, legacy_paths)
        catalog = self._empty_catalog()
        known_ids = set()
        known_directories = set()
        cache = legacy_state.get('profile', {}).get('info_cache', {})

        for profile_id, info in cache.items():
            record = self._legacy_record(profile_id, info)
            directory_key = record['profile_directory'].casefold()
            if record['profile_id'].casefold() in known_ids or directory_key in known_directories:
                raise ProfileManagerError("Duplicate profile metadata in the legacy Local State.")
            catalog['profiles'].append(record)
            known_ids.add(record['profile_id'].casefold())
            known_directories.add(directory_key)

        for path in [*managed_paths, *legacy_paths]:
            profile_id = path.name
            folded_id = profile_id.casefold()
            directory_key = metadata_path_for_profile(path).casefold()
            if directory_key in known_directories:
                continue
            if folded_id in known_ids:
                # The legacy registry already owns this ID. Keep its explicit
                # mapping rather than guessing a replacement directory.
                continue
            record = self._record(profile_id, profile_id, path)
            catalog['profiles'].append(record)
            known_ids.add(folded_id)
            known_directories.add(directory_key)

        self.metadata.save(catalog)
        self._legacy_mirror_enabled = True
        return catalog

    def _reconcile_managed_profiles(self, catalog):
        """Import valid managed folders absent from an existing catalog."""
        known_ids = {record['profile_id'].casefold() for record in catalog['profiles']}
        known_directories = {record['profile_directory'].casefold() for record in catalog['profiles']}
        changed = False
        for path in self._scan_profile_root(PROFILES_DIR):
            directory_key = metadata_path_for_profile(path).casefold()
            if directory_key in known_directories:
                continue
            # If the same ID was already recorded against a missing legacy
            # path, physical managed data takes precedence for recovery.
            matching = next((record for record in catalog['profiles']
                             if record['profile_id'].casefold() == path.name.casefold()), None)
            if matching is not None:
                old_path = profile_path_from_metadata(matching['profile_directory'])
                if not old_path.exists():
                    matching['profile_directory'] = metadata_path_for_profile(path)
                    changed = True
                continue
            if path.name.casefold() in known_ids:
                continue
            catalog['profiles'].append(self._record(path.name, path.name, path))
            known_ids.add(path.name.casefold())
            known_directories.add(directory_key)
            changed = True
        return changed

    def _reconcile_legacy_profiles(self, catalog):
        """Import newly discovered legacy records without making them primary."""
        if not LOCAL_STATE.exists():
            return False
        try:
            legacy_state = self.local_state.load()
        except ProfileManagerError:
            logger.warning("Ignoring unreadable legacy Local State because profiles.json is already available")
            return False
        known_ids = {record['profile_id'].casefold() for record in catalog['profiles']}
        known_directories = {record['profile_directory'].casefold() for record in catalog['profiles']}
        changed = False
        for profile_id, info in legacy_state.get('profile', {}).get('info_cache', {}).items():
            if profile_id.casefold() in known_ids:
                continue
            record = self._legacy_record(profile_id, info)
            directory_key = record['profile_directory'].casefold()
            if directory_key in known_directories:
                continue
            catalog['profiles'].append(record)
            known_ids.add(profile_id.casefold())
            known_directories.add(directory_key)
            changed = True
        return changed

    def _load_catalog(self):
        catalog = self.metadata.load()
        if catalog is None:
            return self._bootstrap_catalog()
        changed = self._reconcile_legacy_profiles(catalog)
        changed = self._reconcile_managed_profiles(catalog) or changed
        if changed:
            self.metadata.save(catalog)
        return catalog

    def initialize_metadata(self):
        """Bootstrap or validate profiles.json during application startup."""
        with self.local_state.operation():
            self._check_registry_idle()
            self._load_catalog()

    def get_profile_metadata(self):
        """Return application metadata records without exposing mutable storage."""
        return [dict(record) for record in self._load_catalog()['profiles']]

    def _legacy_info_for_record(self, record, existing=None):
        info = dict(existing or {})
        info['name'] = record['display_name']
        try:
            info['created'] = int(datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).timestamp())
        except (AttributeError, TypeError, ValueError, OverflowError):
            info['created'] = 0
        path = profile_path_from_metadata(record['profile_directory'])
        if path.absolute().is_relative_to(Path(PROFILES_DIR).absolute()):
            info[MANAGER_PATH_KEY] = path.name
        else:
            info.pop(MANAGER_PATH_KEY, None)
        return info

    def _sync_legacy_registry(self, catalog):
        """Maintain the pre-M4 registry as a compatibility mirror when active."""
        if not self._legacy_mirror_enabled:
            return None
        try:
            state = self.local_state.load()
        except ProfileManagerError:
            # profiles.json is authoritative after bootstrap. A damaged or
            # removed compatibility mirror must not block profile operations.
            logger.warning("Skipping legacy Local State mirror update because it is unreadable")
            self._legacy_mirror_enabled = False
            return None
        cache = state['profile']['info_cache']
        existing = {profile_id: dict(info) for profile_id, info in cache.items()}
        state['profile']['info_cache'] = {
            record['profile_id']: self._legacy_info_for_record(record, existing.get(record['profile_id']))
            for record in catalog['profiles']
        }
        self.local_state.save(state)
        return state

    def _restore_legacy_registry(self, original_bytes):
        """Restore the compatibility mirror if profiles.json publication fails."""
        try:
            if original_bytes is None:
                if LOCAL_STATE.exists():
                    LOCAL_STATE.unlink()
                self.local_state._loaded_bytes = None
                return
            LOCAL_STATE.parent.mkdir(parents=True, exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='wb', dir=LOCAL_STATE.parent,
                                                 prefix='.local-state-rollback-', suffix='.tmp', delete=False) as temp:
                    temp_path = Path(temp.name)
                    temp.write(original_bytes)
                    temp.flush()
                    os.fsync(temp.fileno())
                temp_path.replace(LOCAL_STATE)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
            self.local_state._loaded_bytes = original_bytes
        except OSError as error:
            logger.error(f"Could not restore the legacy Local State mirror: {error}")

    def _save_catalog(self, catalog):
        """Publish application metadata and the optional legacy mirror safely."""
        original_legacy = None
        mirror_attempted = False
        try:
            if self._legacy_mirror_enabled:
                original_legacy = LOCAL_STATE.read_bytes() if LOCAL_STATE.exists() else None
                mirror_attempted = True
                self._sync_legacy_registry(catalog)
            self.metadata.save(catalog)
        except Exception:
            if mirror_attempted:
                self._restore_legacy_registry(original_legacy)
            raise

    def get_profiles(self):
        """Return list of (profile_id, display_name) sorted by name."""
        records = self._load_catalog()['profiles']
        
        profiles = []
        for record in records:
            profiles.append((record['profile_id'], record['display_name']))
        
        # Sort alphabetically by display name
        profiles.sort(key=lambda x: x[1].lower())
        
        # Ensure Default is first if exists
        default_profiles = [p for p in profiles if p[0] == "Default"]
        other_profiles = [p for p in profiles if p[0] != "Default"]
        profiles = default_profiles + other_profiles
        
        return profiles
    
    def next_profile_id(self, cache):
        """Generate a collision-free ID for a profile in the new profiles root."""
        max_num = 0

        candidates = list(cache) if isinstance(cache, dict) else []
        for info in cache.values() if isinstance(cache, dict) else []:
            if not isinstance(info, dict):
                continue
            if isinstance(info.get(MANAGER_PATH_KEY), str):
                candidates.append(info[MANAGER_PATH_KEY])
            if isinstance(info.get('profile_directory'), str):
                try:
                    candidates.append(profile_path_from_metadata(info['profile_directory']).name)
                except ProfileManagerError:
                    pass
        if PROFILES_DIR.is_dir():
            candidates.extend(path.name for path in PROFILES_DIR.iterdir())
        if DATA_DIR.is_dir():
            candidates.extend(path.name for path in DATA_DIR.iterdir())
        for candidate in candidates:
            match = NEW_PROFILE_PATTERN.fullmatch(candidate)
            if match:
                max_num = max(max_num, int(match.group(1)))
                continue
            pending = re.match(r'^\.deleting-(profile_\d+)-', candidate, re.IGNORECASE)
            if pending:
                max_num = max(max_num, int(pending.group(1).split('_', 1)[1]))

        return f"profile_{max_num + 1:04d}"
    
    def create_profile(self, display_name=None):
        """Create a new profile and initialize it"""
        if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
            raise ProfileManagerError("Profile name must not be empty.")
        with self.local_state.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            new_id = self.next_profile_id(self._record_map(catalog))
            self._initialize_profile_structure(new_id)
            profile_dir = self._resolve_profile_dir(new_id)
            catalog['profiles'].append(self._record(
                new_id,
                display_name.strip() if display_name is not None else new_id,
                profile_dir,
            ))
            # Publish only after initialization. Failed creations are never reused.
            try:
                self._save_catalog(catalog)
            except Exception:
                self._unpublished_paths.add(profile_dir.absolute())
                raise
            logger.info(f"Profile {new_id} created successfully")
            return new_id
    
    def _initialize_profile_structure(self, profile_id):
        """Create minimal Chromium profile structure without launching browser"""

        profile_dir = self._resolve_profile_dir(profile_id)
        profile_dir.parent.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(exist_ok=False)

        # Minimal Preferences file
        browser_profile = profile_dir / 'Default'
        browser_profile.mkdir()
        prefs_file = browser_profile / "Preferences"

        if not prefs_file.exists():
            minimal_prefs = {
                "profile": {
                    "name": profile_id
                },
                "extensions": {
                    "ui": {
                        "developer_mode": True
                    }
                }
            }

            with open(prefs_file, "w", encoding="utf-8") as f:
                json.dump(minimal_prefs, f, indent=2)

        # Create extension folder early (optional but recommended)
        (profile_dir / "Unpacked Extensions").mkdir(exist_ok=True)

        logger.info(f"Profile structure created manually for {profile_id}")
    
    def _terminate_process_tree(self, pid):
        """Terminate process and all its children"""
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            
            # Wait for termination
            gone, alive = psutil.wait_procs([parent] + parent.children(), timeout=3)
            for p in alive:
                p.kill()
                
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.warning(f"Error terminating process tree: {e}")
    
    def rename_profile(self, profile_id, new_name):
        """Rename a profile"""
        if not isinstance(new_name, str) or not new_name.strip():
            raise ProfileManagerError("Profile name must not be empty.")
        with self.local_state.operation():
            self._check_registry_idle()
            self.require_profile_dir(profile_id)
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
            record['display_name'] = new_name.strip()
            self._save_catalog(catalog)
        logger.info(f"Profile {profile_id} renamed to {new_name}")
    
    def delete_profile(self, profile_id):
        """Delete a profile and its data"""
        profile_id = validate_profile_id(profile_id)
        with self.local_state.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found")
            profile_dir = self._resolve_profile_dir(profile_id, record)
            if browser_using_directory(profile_dir):
                raise ProfileManagerError(f"Close Chromium for {profile_id} before deleting it.")
            pending = None
            if profile_dir.exists():
                if not profile_dir.is_dir():
                    raise ProfileManagerError(f"Profile path is not a directory: {profile_dir}")
                pending = checked_path(profile_dir.parent / f'.deleting-{profile_id}-{uuid.uuid4().hex}', profile_dir.parent)
                profile_dir.rename(pending)
            else:
                self._check_pending_delete(profile_id, profile_dir.parent)
            catalog['profiles'] = [item for item in catalog['profiles']
                                   if item['profile_id'] != profile_id]
            try:
                self._save_catalog(catalog)
            except Exception:
                if pending is not None:
                    if profile_dir.exists():
                        raise ProfileManagerError(f"Deletion was interrupted. Profile data is preserved at {pending}; restore it before retrying.")
                    pending.rename(profile_dir)
                raise
            if pending is not None:
                # Resolve and verify the recursive deletion target immediately beforehand.
                checked_path(pending, pending.parent)
                try:
                    shutil.rmtree(pending)
                except OSError as error:
                    raise ProfileManagerError(f"Profile was removed from the list, but some data could not be deleted at {pending}. No further cleanup will run automatically.") from error
            logger.info(f"Deleted profile {profile_id}")
    
    def get_profile_dir(self, profile_id):
        """Get profile directory path"""
        profile_id = validate_profile_id(profile_id)
        catalog = self.metadata.load()
        if catalog is None and not LOCAL_STATE.exists() and not DATA_DIR.exists() and not PROFILES_DIR.exists():
            # Preserve the read-only path helper behavior for callers that
            # only need to construct a launch error; require_profile_dir()
            # still enforces registration before any browser starts.
            return self._resolve_profile_dir(profile_id)
        record = self._record_map(self._load_catalog()).get(profile_id)
        if record is None:
            return self._resolve_profile_dir(profile_id)
        return self._resolve_profile_dir(profile_id, record)

    def _resolve_profile_dir(self, profile_id, info=None):
        """Resolve a profile to its managed directory without moving any data."""
        profile_id = validate_profile_id(profile_id)
        if info is not None and 'profile_directory' in info:
            return profile_path_from_metadata(info['profile_directory'])
        if info is not None and MANAGER_PATH_KEY in info:
            manager_path = validate_manager_path(info[MANAGER_PATH_KEY])
            return checked_path(PROFILES_DIR / manager_path, PROFILES_DIR)

        # An unmarked entry is a legacy profile. Prefer it when present, even
        # if its old ID happens to resemble the new profile_#### convention.
        legacy_path = checked_path(DATA_DIR / profile_id, DATA_DIR)
        if legacy_path.exists() or not NEW_PROFILE_PATTERN.fullmatch(profile_id):
            return legacy_path
        return checked_path(PROFILES_DIR / profile_id, PROFILES_DIR)

    def _check_registry_idle(self):
        for root, label in ((DATA_DIR, 'legacy'), (PROFILES_DIR, 'managed')):
            if browser_using_directory(root, exact=True):
                raise ProfileManagerError(f"Chromium is using the shared {label} data directory. Close it before using the manager.")

    def _check_pending_delete(self, profile_id, parent=None):
        roots = [parent] if parent is not None else [DATA_DIR, PROFILES_DIR]
        for root in roots:
            if not root.exists():
                continue
            for path in root.iterdir():
                if path.name.startswith(f'.deleting-{profile_id}-'):
                    raise ProfileManagerError(f"An interrupted deletion left data at {path}. Restore or inspect that directory before continuing.")

    def require_profile_dir(self, profile_id):
        profile_id = validate_profile_id(profile_id)
        if (self.metadata.load() is None and not LOCAL_STATE.exists()
                and not DATA_DIR.exists() and not PROFILES_DIR.exists()):
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        record = self._record_map(self._load_catalog()).get(profile_id)
        if record is None:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        path = self._resolve_profile_dir(profile_id, record)
        if not path.is_dir():
            self._check_pending_delete(profile_id, path.parent)
            raise ProfileNotFoundError(f"Profile directory is missing or invalid: {path}. Restore it before opening; no replacement profile was created.")
        return path

    def migrate_profile(self, profile_id):
        """Copy one legacy profile into profiles/ without altering its source."""
        profile_id = validate_profile_id(profile_id)
        with self.local_state.operation():
            self._check_registry_idle()
            catalog = self._load_catalog()
            record = self._record_map(catalog).get(profile_id)
            if record is None:
                raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")

            current_path = self._resolve_profile_dir(profile_id, record)
            if current_path.absolute().is_relative_to(Path(PROFILES_DIR).absolute()):
                managed_id = current_path.name
                destination = checked_path(current_path, PROFILES_DIR)
                if not destination.is_dir():
                    raise ProfileManagerError(
                        f"Profile {profile_id} is marked as migrated, but its managed directory is missing: {destination}. "
                        "The legacy source was left untouched."
                    )
                return managed_id

            source = checked_path(DATA_DIR / profile_id, DATA_DIR)
            if not source.exists():
                self._check_pending_delete(profile_id, source.parent)
                raise ProfileManagerError(f"Legacy profile directory is missing: {source}. No migration was performed.")
            if not source.is_dir():
                raise ProfileManagerError(f"Legacy profile path is not a directory: {source}. No migration was performed.")
            if browser_using_directory(source):
                raise ProfileManagerError(f"Close Chromium for {profile_id} before migrating it.")
            destination = None
            try:
                ensure_tree_has_no_links(source)
                checked_path(PROFILES_DIR, PROJECT_ROOT)
                PROFILES_DIR.mkdir(parents=True, exist_ok=True)
                new_id = self.next_profile_id(self._record_map(catalog))
                destination = checked_path(PROFILES_DIR / new_id, PROFILES_DIR)
                if destination.exists():
                    raise ProfileManagerError(f"Cannot migrate {profile_id}: destination already exists at {destination}.")
                shutil.copytree(source, destination)
            except ProfileManagerError:
                raise
            except (OSError, shutil.Error) as error:
                partial = f" A partial copy may remain at {destination}." if destination is not None else " No destination was created."
                raise ProfileManagerError(
                    f"Profile migration failed. The legacy source was left untouched at {source}.{partial}"
                ) from error

            try:
                record['profile_directory'] = metadata_path_for_profile(destination)
                self._save_catalog(catalog)
            except Exception as error:
                self._unpublished_paths.add(destination.absolute())
                raise ProfileManagerError(
                    f"Profile data was copied to {destination}, but metadata could not be updated. "
                    f"The legacy source remains untouched at {source}; remove nothing automatically and retry after fixing Local State."
                ) from error
            logger.info(f"Migrated legacy profile {profile_id} to {destination}")
            return new_id

    def mark_profile_opened(self, profile_id, catalog=None):
        """Update last_opened_at for a successful launch.

        Chromium is already launched when the launcher calls this while its
        existing operation lock is held, so the optional catalog avoids a
        nested lock acquisition.
        """
        if catalog is None:
            with self.local_state.operation():
                self._check_registry_idle()
                catalog = self._load_catalog()
                self._mark_profile_opened(catalog, profile_id)
                self._save_catalog(catalog)
            return
        self._mark_profile_opened(catalog, profile_id)
        self._save_catalog(catalog)

    def _mark_profile_opened(self, catalog, profile_id):
        record = self._record_map(catalog).get(profile_id)
        if record is None:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        record['last_opened_at'] = utc_timestamp()

    def get_browser_profile_dir(self, profile_id):
        """Validate an existing independent user-data root without migrating it."""
        root = self.require_profile_dir(profile_id)
        flat_markers = ('Cookies', 'Network', 'Local Storage', 'IndexedDB', 'Login Data',
                        'History', 'Bookmarks', 'Sessions', 'Session Storage', 'Web Data', 'Service Worker')
        if any((root / marker).exists() for marker in flat_markers):
            raise ProfileManagerError(f"Legacy browser data is directly inside {root}. This appears to be a shared-root subprofile, not an isolated user-data directory. M2 will not relocate it or open an empty replacement.")
        browser_state = checked_path(root / 'Local State', root)
        last_used = 'Default'
        if browser_state.exists():
            try:
                data = json.loads(browser_state.read_text(encoding='utf-8-sig'), object_pairs_hook=LocalStateManager._unique_keys)
                if not isinstance(data, dict) or not isinstance(data.get('profile', {}), dict):
                    raise ValueError('Invalid browser Local State')
                last_used = validate_profile_id(data.get('profile', {}).get('last_used', 'Default'))
            except (OSError, ValueError, UnicodeError) as error:
                raise ProfileManagerError(f"Cannot read Chromium state at {browser_state}. Restore it before opening this profile.") from error
        browser_profile = checked_path(root / last_used, root)
        if last_used != 'Default' and not browser_profile.is_dir():
            raise ProfileManagerError(f"Chromium's last-used profile directory is missing: {browser_profile}")
        if not browser_profile.exists():
            for child in root.iterdir():
                if child.is_dir() and child.name != 'Unpacked Extensions' and (child / 'Preferences').exists():
                    raise ProfileManagerError(f"Ambiguous Chromium profile layout at {root}. No new profile will be created.")
        elif not browser_profile.is_dir():
            raise ProfileManagerError(f"Chromium profile path is not a directory: {browser_profile}")
        checked_path(browser_profile / 'Preferences', root)
        return browser_profile

# ----------------------------------------------------------------------
# Extension and Account Management
# ----------------------------------------------------------------------
class ExtensionManager:
    """Discover and safely deploy the supported unpacked extension."""

    def __init__(self, profile_manager):
        self.profile_manager = profile_manager

    @staticmethod
    def _source_root():
        # Derive the root from EXT_DIR so tests and portable copies can replace
        # the source location without introducing an absolute path dependency.
        return Path(EXT_DIR).parent

    @staticmethod
    def _profile_extensions_dir(profile_dir):
        return checked_path(
            Path(profile_dir) / PROFILE_EXTENSIONS_DIR_NAME,
            profile_dir,
        )

    @staticmethod
    def _declared_file(extension_dir, relative_name, description):
        if not isinstance(relative_name, str) or not relative_name.strip():
            raise ExtensionError(f"{description} declares an invalid file path.")
        relative = PureWindowsPath(relative_name.replace('/', '\\'))
        if relative.is_absolute() or relative.drive or any(
                part in ('', '.', '..') for part in relative.parts):
            raise ExtensionError(f"{description} declares an unsafe file path.")
        candidate = checked_path(extension_dir.joinpath(*relative.parts), extension_dir)
        if not candidate.is_file():
            raise ExtensionError(f"{description} is missing {relative_name}.")
        return candidate

    @classmethod
    def _validate_extension_directory(cls, extension_dir, description):
        extension_dir = Path(extension_dir)
        if not extension_dir.is_dir():
            raise ExtensionError(f"{description} is not a directory.")
        try:
            ensure_tree_has_no_links(extension_dir)
        except ProfileManagerError as error:
            raise ExtensionError(f"{description} contains an unsupported linked path.") from error

        manifest_file = extension_dir / 'manifest.json'
        config_file = extension_dir / 'config.js'
        if not manifest_file.is_file():
            raise ExtensionError(f"{description} is incomplete: manifest.json is missing.")
        if not config_file.is_file():
            raise ExtensionError(f"{description} is incomplete: config.js is missing.")

        try:
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as error:
            raise ExtensionError(f"{description} has an unreadable manifest.json.") from error

        if not isinstance(manifest, dict) or manifest.get('manifest_version') != 3:
            raise ExtensionError(f"{description} has an unsupported manifest.json.")

        content_scripts = manifest.get('content_scripts', [])
        if not isinstance(content_scripts, list):
            raise ExtensionError(f"{description} has an invalid content_scripts section.")
        for script in content_scripts:
            if not isinstance(script, dict):
                raise ExtensionError(f"{description} has an invalid content script entry.")
            scripts = script.get('js', [])
            if not isinstance(scripts, list):
                raise ExtensionError(f"{description} has an invalid content script list.")
            for relative_name in scripts:
                cls._declared_file(extension_dir, relative_name, description)

        icons = manifest.get('icons', {})
        if icons is not None:
            if not isinstance(icons, dict):
                raise ExtensionError(f"{description} has an invalid icons section.")
            for relative_name in icons.values():
                cls._declared_file(extension_dir, relative_name, description)
        return manifest

    def get_source_path(self):
        return Path(EXT_DIR)

    def discover_sources(self):
        """Return valid supported extension sources under the project root."""
        source = self.get_source_path()
        if not source.exists():
            return {}
        checked_path(source, self._source_root())
        self._validate_extension_directory(source, 'Autofill extension source')
        return {AUTOFILL_EXTENSION_NAME: source}

    # Short alias for callers that use discovery as a verb.
    discover = discover_sources

    def profile_extension_path(self, profile_id):
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        extensions_dir = self._profile_extensions_dir(profile_dir)
        return checked_path(
            extensions_dir / AUTOFILL_EXTENSION_NAME,
            profile_dir,
        )

    def get_profile_extension_paths(self, profile_id):
        """Return a valid existing deployment, or no optional extension."""
        # Keep launch error ordering compatible with M1: the launcher reports a
        # missing browser runtime before an unknown profile. This helper only
        # inspects an already-resolved directory and never creates one.
        profile_dir = self.profile_manager.get_profile_dir(profile_id)
        if not profile_dir.is_dir():
            return []
        target = checked_path(
            self._profile_extensions_dir(profile_dir) / AUTOFILL_EXTENSION_NAME,
            profile_dir,
        )
        if not target.exists():
            return []
        try:
            self._validate_extension_directory(
                target,
                f"Profile {profile_id} extension deployment",
            )
        except ExtensionError as error:
            # An optional extension must never prevent the browser profile from
            # opening. The account data remains in the profile and is not changed.
            logger.warning("Skipping invalid optional extension deployment for profile %s: %s", profile_id, error)
            return []
        return [target]

    @staticmethod
    def _remove_path(path):
        path = Path(path)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    def ensure_profile_extension(self, profile_id):
        """Deploy current reusable source while preserving profile config.js."""
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        source = self.get_source_path()
        if not source.exists():
            raise ExtensionNotFoundError(f"Autofill extension source not found at {source}")
        self._validate_extension_directory(source, 'Autofill extension source')

        extensions_dir = self._profile_extensions_dir(profile_dir)
        extensions_dir.mkdir(parents=True, exist_ok=True)
        target = checked_path(extensions_dir / AUTOFILL_EXTENSION_NAME, profile_dir)
        if target.exists() and not target.is_dir():
            raise ExtensionDeploymentError(
                f"Profile {profile_id} extension deployment is not a directory."
            )

        existing_config = None
        if target.is_dir():
            ensure_tree_has_no_links(target)
            if (target / 'config.js').is_file():
                existing_config = (target / 'config.js').read_bytes()

        staging = checked_path(
            extensions_dir / f".{AUTOFILL_EXTENSION_NAME}.staging-{uuid.uuid4().hex}",
            profile_dir,
        )
        backup = checked_path(
            extensions_dir / f".{AUTOFILL_EXTENSION_NAME}.backup-{uuid.uuid4().hex}",
            profile_dir,
        )
        moved_to_backup = False
        try:
            shutil.copytree(source, staging)
            staged_config = checked_path(staging / 'config.js', staging)
            if existing_config is not None:
                staged_config.write_bytes(existing_config)

            # Preserve profile-local files unknown to the reusable source. The
            # known profile-specific config is handled explicitly above.
            if target.is_dir():
                for current, _, files in os.walk(target, followlinks=False):
                    for name in files:
                        existing = Path(current) / name
                        relative = existing.relative_to(target)
                        if relative == Path('config.js'):
                            continue
                        destination = checked_path(staging / relative, staging)
                        if not destination.exists():
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(existing, destination)

            self._validate_extension_directory(staging, 'Staged autofill extension')
            if target.exists():
                target.replace(backup)
                moved_to_backup = True
            staging.replace(target)
            if backup.exists():
                try:
                    self._remove_path(backup)
                except OSError:
                    logger.warning("Old extension deployment could not be cleaned for profile %s", profile_id)
            return target
        except ExtensionError:
            raise
        except (OSError, shutil.Error) as error:
            raise ExtensionDeploymentError(
                f"Could not deploy the autofill extension for profile {profile_id}."
            ) from error
        finally:
            if staging.exists():
                try:
                    self._remove_path(staging)
                except OSError:
                    logger.warning("Temporary extension deployment could not be cleaned")
            if moved_to_backup and backup.exists() and not target.exists():
                try:
                    backup.replace(target)
                except OSError:
                    logger.error("Previous extension deployment could not be restored for profile %s", profile_id)


class AccountManager:
    """Manage Discord account credentials in extension"""
    
    def __init__(self, profile_manager):
        self.profile_manager = profile_manager
        self.extension_manager = ExtensionManager(profile_manager)

    def _ensure_extension_installed(self, profile_id):
        """Ensure the supported autofill extension is safely deployed."""
        return self.extension_manager.ensure_profile_extension(profile_id)

    def _ensure_both_extensions_installed(self, profile_id):
        """Compatibility name retained for callers from the pre-M5 workflow."""
        return [self._ensure_extension_installed(profile_id)]
    
    def _get_config_path(self, profile_id):
        """Get path to config.js for profile"""
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        ext_dir = self.extension_manager.profile_extension_path(profile_id)
        return checked_path(ext_dir / "config.js", profile_dir)
    
    def _enable_developer_mode(self, profile_id):
        """Enable developer mode in profile preferences"""
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        if browser_using_directory(profile_dir):
            raise ProfileManagerError("Close this profile's Chromium windows before configuring its account.")
        prefs_file = self.profile_manager.get_browser_profile_dir(profile_id) / "Preferences"
        
        if not prefs_file.exists():
            logger.warning(f"Preferences not found for {profile_id}")
            return
        
        try:
            # Read preferences
            with open(prefs_file, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
            
            # Set developer mode
            if "extensions" not in prefs:
                prefs["extensions"] = {}
            prefs["extensions"].setdefault("ui", {})["developer_mode"] = True
            
            # Write safely
            temp_file = checked_path(prefs_file.with_suffix('.tmp'), profile_dir)
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(prefs, f, indent=2)
            temp_file.replace(prefs_file)
            
            logger.info(f"Developer mode enabled for {profile_id}")
            
        except Exception as e:
            logger.error(f"Failed to enable developer mode: {e}")
            raise ProfileManagerError(f"Cannot enable developer mode: {e}")
    
    def set_account(self, profile_id, account_string):
        """Set Discord account for profile"""
        logger.info(f"Setting account for profile {profile_id}")
        
        # Validate format
        def _normalize(text):
            if not text:
                return ""
            return re.sub(r"\s+", "", text.strip())

        parts = account_string.strip().split(':')

        if len(parts) < 2:
            raise InvalidAccountFormatError(
                "Format must be email:password hoặc email:password:2faSecret"
            )

        email = _normalize(parts[0])
        password = _normalize(parts[1])
        totp_secret = _normalize(parts[2]) if len(parts) > 2 else ""

        if not email or not password:
            raise InvalidAccountFormatError("Email và password không được để trống")

        if totp_secret:
            totp_secret = totp_secret.upper()
        
        # Deploy the reusable source and retain this profile's existing config
        # until the new account configuration is written below.
        self._ensure_extension_installed(profile_id)
        
        # Enable developer mode
        self._enable_developer_mode(profile_id)
        
        # Create profile-specific config.js. JSON encoding keeps account values
        # from changing the JavaScript structure when special characters occur.
        config_content = f"""// Discord Auto-fill Extension Configuration
const ACCOUNT = {{
    email: {json.dumps(email, ensure_ascii=True)},
    password: {json.dumps(password, ensure_ascii=True)},
    totpSecret: {json.dumps(totp_secret, ensure_ascii=True)}
}};
"""
        
        config_file = self._get_config_path(profile_id)
        temp_file = checked_path(
            config_file.with_name(f".config-{uuid.uuid4().hex}.tmp"),
            config_file.parent,
        )
        try:
            with open(temp_file, 'w', encoding='utf-8', newline='') as f:
                f.write(config_content)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(config_file)
        except (OSError, UnicodeError) as error:
            raise ProfileManagerError(
                f"Could not save the account configuration for profile {profile_id}."
            ) from error
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    logger.warning("Temporary account configuration could not be cleaned")
        
        logger.info(f"Account configured for profile {profile_id}")
    
    def get_account(self, profile_id):
        """Get account information from config.js"""
        config_file = self._get_config_path(profile_id)
        
        if not config_file.exists():
            return None
        
        try:
            content = config_file.read_text(encoding='utf-8')
            values = {}
            for field in ('email', 'password', 'totpSecret'):
                match = re.search(
                    rf'\b{field}\s*:\s*("(?:\\.|[^"\\])*")',
                    content,
                )
                if not match:
                    return None
                try:
                    values[field] = json.loads(match.group(1))
                except (TypeError, ValueError):
                    return None

            email = values['email'].strip()
            password = values['password'].strip()
            totp = values['totpSecret'].strip()
            if email and password:
                return {
                    'email': email,
                    'password': password,
                    'totp_secret': totp
                }
        except (OSError, UnicodeError):
            # Do not include configuration contents or exception text in logs.
            logger.warning("Could not read autofill configuration for profile %s", profile_id)
        
        return None
    
    def remove_account(self, profile_id):
        """Remove account from config.js"""
        config_file = self._get_config_path(profile_id)
        
        if config_file.exists():
            # Reset to empty config
            empty_config = """// Discord Auto-fill Extension Configuration
const ACCOUNT = {
    email: "",
    password: "",
    totpSecret: ""
};
"""
            temp_file = checked_path(
                config_file.with_name(f".config-{uuid.uuid4().hex}.tmp"),
                config_file.parent,
            )
            try:
                with open(temp_file, 'w', encoding='utf-8', newline='') as f:
                    f.write(empty_config)
                    f.flush()
                    os.fsync(f.fileno())
                temp_file.replace(config_file)
            finally:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        logger.warning("Temporary account configuration could not be cleaned")
            
            logger.info(f"Account removed for profile {profile_id}")
    
    # -----------------------------
    # Mask helpers
    # -----------------------------

    def mask_email(self, email):
        if not email or "@" not in email:
            return "***"

        name, domain = email.split("@", 1)

        if len(name) <= 2:
            masked = "*" * len(name)
        else:
            masked = name[:2] + "*" * (len(name) - 2)

        return f"{masked}@{domain}"


    def mask_password(self, password):
        if not password:
            return "Not set"

        return "•" * max(len(password), 8)


    def mask_totp(self, totp):
        if not totp:
            return "Not set"

        return "•" * max(len(totp), 6)

# ----------------------------------------------------------------------
# Chromium Launcher
# ----------------------------------------------------------------------
class ChromiumLauncher:
    """Handle Chromium launching with proper arguments"""
    
    def __init__(self):
        self.launcher_path = BROWSER_EXE
        self._processes = {}
        
    def launch_discord(self, profile_id, extension_paths=None):
        """Launch Discord with specified profile and multiple extensions"""
        if not self.launcher_path.is_file():
            raise ProfileManagerError(
                f"Chromium browser runtime not found. Expected executable:\n{self.launcher_path}"
            )

        profiles = ProfileManager()
        with profiles.local_state.operation():
            profiles._check_registry_idle()
            catalog = profiles._load_catalog()
            profile_data_dir = profiles.require_profile_dir(profile_id)
            previous = self._processes.get(profile_id)
            if (previous is not None and previous.poll() is None) or browser_using_directory(profile_data_dir):
                return False
            profiles.get_browser_profile_dir(profile_id)

            cmd = [
                str(self.launcher_path),
                f"--user-data-dir={profile_data_dir}",
                "--new-window",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--process-per-site",
                "https://discord.com/app"
            ]

            if extension_paths:
                valid_paths = [str(checked_path(p, profile_data_dir)) for p in extension_paths if p and p.exists()]
                if any(',' in path for path in valid_paths):
                    raise ProfileManagerError("Extension paths containing commas cannot be loaded safely. Move the application folder to a path without commas.")
                if valid_paths:
                    joined = ','.join(valid_paths)
                    cmd.extend([f"--disable-extensions-except={joined}", f"--load-extension={joined}"])

            logger.info(f"Requesting Chromium launch for profile {profile_id}")
            try:
                process = subprocess.Popen(
                    cmd,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if process.poll() not in (None, 0):
                    raise ProfileManagerError(f"Chromium exited before opening profile {profile_id}.")
                self._processes[profile_id] = process
                profiles.mark_profile_opened(profile_id, catalog)
                return True
            except OSError as error:
                raise ProfileManagerError(f"Cannot launch Chromium: {error}") from error

# ----------------------------------------------------------------------
# GUI Application
# ----------------------------------------------------------------------
class ProfileManagerApp:
    """Main GUI application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Discord Profile Manager")
        self.root.geometry("1100x650")
        self.root.minsize(850, 450)
        self.root.configure(bg='#f0f0f0')
        
        # Initialize managers
        self.profile_manager = ProfileManager()
        self.account_manager = AccountManager(self.profile_manager)
        self.launcher = ChromiumLauncher()
        
        # Variables
        self.profiles = []          # list of (pid, name)
        self.current_profile = None
        self.selected_profile_ids = set()
        self.sort_method = tk.StringVar(value="name")
        self.sort_reverse = False
        self.search_var = tk.StringVar()
        self._search_after_id = None
        self._status_after_id = None
        self._profile_rows = []
        self._closing = False
        self.table_rows = []
        
        # Setup UI
        self.setup_ui()
        
        # Load profiles
        self.refresh_list()
        self._schedule_status_poll()
        
        logger.info("Application started")
    
    def setup_ui(self):
        """Setup user interface"""
        # Main container (left + right)
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # ----- LEFT SIDE: Profile list and sorting -----
        left_frame = tk.Frame(main_frame, bg='#f0f0f0')
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Search and sorting controls
        search_frame = tk.Frame(left_frame, bg='#f0f0f0')
        search_frame.pack(fill=tk.X, pady=(0, 5))

        tk.Label(
            search_frame,
            text="Search:",
            bg='#f0f0f0',
            font=('Helvetica', 9, 'bold')
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.search_var.trace_add("write", self._schedule_search_filter)

        # Sorting options
        sort_frame = tk.Frame(left_frame, bg='#f0f0f0')
        sort_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(sort_frame, text="Sắp xếp:", bg='#f0f0f0',
                font=('Helvetica', 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        for text, value in [("Tên", "name"), ("ID", "id"), ("Mới nhất", "created"), ("Default đầu", "default_first")]:
            rb = tk.Radiobutton(sort_frame, text=text, variable=self.sort_method,
                                value=value, bg='#f0f0f0',
                                command=self.apply_search_filter)
            rb.pack(side=tk.LEFT, padx=5)
        
        # Profile treeview with scrollbar
        tree_frame = tk.Frame(left_frame, bg='#f0f0f0')
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create Treeview with scrollbars
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        xscrollbar = tk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        xscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.tree = ttk.Treeview(
            tree_frame,
            columns=PROFILE_TABLE_DATA_COLUMNS,
            displaycolumns=PROFILE_TABLE_COLUMNS,
            show="headings",  # Hide the default first empty column
            yscrollcommand=scrollbar.set,
            xscrollcommand=xscrollbar.set,
            selectmode="extended",  # Enable multi-selection
            height=15
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure scrollbar
        scrollbar.config(command=self.tree.yview)
        xscrollbar.config(command=self.tree.xview)
        
        # Configure columns
        self.tree.heading("name", text="Tên Profile")
        self.tree.heading("id", text="Profile ID")
        
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("id", width=150, anchor="w")

        headings = {
            "name": "Name",
            "account": "Account",
            "environment": "Environment",
            "proxy": "Proxy",
            "status": "Status",
            "last_opened": "Last Opened",
            "id": "Profile ID",
        }
        widths = {
            "name": 240,
            "account": 220,
            "environment": 105,
            "proxy": 80,
            "status": 100,
            "last_opened": 155,
            "id": 170,
        }
        self._id_column_index = PROFILE_TABLE_DATA_COLUMNS.index("id")
        for column in PROFILE_TABLE_DATA_COLUMNS:
            self.tree.heading(
                column,
                text=headings[column],
                command=lambda selected_column=column: self.sort_by_column(selected_column)
            )
            self.tree.column(
                column,
                width=widths[column],
                anchor="w",
                stretch=column != "id"
            )
        
        # Configure style for better appearance
        style = ttk.Style()
        style.configure("Treeview", font=('Helvetica', 11), rowheight=25)
        style.configure("Treeview.Heading", font=('Helvetica', 10, 'bold'))
        
        # ----- RIGHT SIDE -----
        right_frame = tk.Frame(main_frame, bg='#f0f0f0', width=200)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        right_frame.pack_propagate(False)
        
        btn_style = {
            'font': ('Helvetica', 9, 'bold'),
            'width': 16,
            'padx': 5,
            'pady': 5,
            'relief': tk.RAISED,
            'bd': 2,
            'cursor': 'hand2'
        }
        
        # ===== QUICK ACTION =====
        launch_frame = tk.LabelFrame(
            right_frame,
            text="Quick Launch",
            bg='#f0f0f0',
            font=('Helvetica', 10, 'bold'),
            padx=5,
            pady=5
        )
        launch_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_open_discord = tk.Button(
            launch_frame,
            text="🚀 MỞ DISCORD",
            command=self.open_discord,
            bg='#5865F2',
            fg='white',
            activebackground='#4752C4',
            activeforeground='white',
            font=('Helvetica', 11, 'bold'),
            pady=8,
            cursor='hand2'
        )
        self.btn_open_discord.pack(fill=tk.X)

        # ===== MANAGER ACTIONS =====
        manager_frame = tk.LabelFrame(
            right_frame,
            text="Manager Actions",
            bg='#f0f0f0',
            font=('Helvetica', 9, 'bold'),
            padx=5,
            pady=5
        )
        manager_frame.pack(fill=tk.X, pady=(0, 8))

        manager_buttons = [
            ("⭕ Làm mới", self.refresh_list, '#6C757D', '#545B62'),
            ("🔷 Select All", self.select_all_profiles, '#17A2B8', '#138496'),
            ("🧹 Deselect All", self.deselect_all_selection, "#658B32", "#5BB428"),
            ("📂 Import TXT", self.bulk_import_profiles, '#17A2B8', '#138496'),
        ]

        for text, cmd, bg, activebg in manager_buttons:
            button = tk.Button(
                manager_frame,
                text=text,
                command=cmd,
                bg=bg,
                fg='white',
                activebackground=activebg,
                activeforeground='white',
                **btn_style
            )
            button.pack(pady=3, fill=tk.X)
            button_names = {
                "refresh_list": "btn_refresh",
                "select_all_profiles": "btn_select_all",
                "deselect_all_selection": "btn_deselect_all",
                "bulk_import_profiles": "btn_import_profiles",
            }
            attribute = button_names.get(getattr(cmd, "__name__", ""))
            if attribute:
                setattr(self, attribute, button)

        # ===== PROFILE ACTIONS =====
        profile_frame = tk.LabelFrame(
            right_frame,
            text="Profile Actions",
            bg='#f0f0f0',
            font=('Helvetica', 9, 'bold'),
            padx=5,
            pady=5
        )
        profile_frame.pack(fill=tk.X, pady=(0, 8))
        
        profile_buttons = [
            ("Edit", self.edit_profile, '#6C757D', '#545B62'),
            ("✨ Tạo Profile", self.create_profile, '#0078D7', '#0053A0'),
            ("✏️ Đổi tên", self.rename_profile, '#28A745', '#1E7E34'),
            ("🗑️ Xóa", self.delete_profile, '#DC3545', '#BD2130'),
        ]
        
        for text, cmd, bg, activebg in profile_buttons:
            button = tk.Button(
                profile_frame,
                text=text,
                command=cmd,
                bg=bg,
                fg='white',
                activebackground=activebg,
                activeforeground='white',
                **btn_style
            )
            button.pack(pady=3, fill=tk.X)
            button_names = {
                "create_profile": "btn_create_profile",
                "rename_profile": "btn_rename_profile",
                "delete_profile": "btn_delete_profile",
                "edit_profile": "btn_edit_profile",
            }
            attribute = button_names.get(getattr(cmd, "__name__", ""))
            if attribute:
                setattr(self, attribute, button)
        
        # ===== ACCOUNT ACTIONS =====
        account_frame = tk.LabelFrame(
            right_frame,
            text="Account Actions",
            bg='#f0f0f0',
            font=('Helvetica', 9, 'bold'),
            padx=5,
            pady=5
        )
        account_frame.pack(fill=tk.X)

        self.btn_set_account = tk.Button(
            account_frame,
            text="🔑 Set Account",
            command=self.set_account,
            bg='#FD7E14',
            fg='white',
            activebackground='#E06B0F',
            activeforeground='white',
            **btn_style
        )
        self.btn_set_account.pack(pady=3, fill=tk.X)

        self.btn_view_account = tk.Button(
            account_frame,
            text="👁️ View Account",
            command=self.view_account,
            bg='#6C757D',
            fg='white',
            activebackground='#545B62',
            activeforeground='white',
            **btn_style
        )
        self.btn_view_account.pack(pady=3, fill=tk.X)

        self.btn_remove_account = tk.Button(
            account_frame,
            text="❌ Remove Account",
            command=self.remove_account,
            bg='#DC3545',
            fg='white',
            activebackground='#BD2130',
            activeforeground='white',
            **btn_style
        )
        self.btn_remove_account.pack(pady=3, fill=tk.X)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Sẵn sàng")
        
        status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,
            bg='#e0e0e0',
            font=('Helvetica', 8),
            padx=5
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind events
        self.tree.bind("<Double-Button-1>", lambda e: self.open_discord())
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    @staticmethod
    def _value(value, default=""):
        """Read a Tk variable or return a plain value for test doubles."""
        if hasattr(value, "get"):
            return value.get()
        return default if value is None else value

    def _display_environment(self, record):
        preset = record.get("environment_preset") or DEFAULT_ENVIRONMENT_PRESET
        if str(preset).casefold() == DEFAULT_ENVIRONMENT_PRESET:
            return "Default"
        return str(preset).replace("_", " ").title()

    @staticmethod
    def _display_proxy(record):
        return "On" if bool(record.get("proxy_enabled", False)) else "Off"

    @staticmethod
    def _display_last_opened(value):
        if not value:
            return "Never"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError):
            return str(value)

    def _account_identifier(self, profile_id):
        """Return the only account field safe for the profile table."""
        try:
            account = self.account_manager.get_account(profile_id)
            email = account.get("email") if isinstance(account, dict) else None
            return str(email) if email else "—"
        except (AttributeError, KeyError, ProfileManagerError, OSError, TypeError):
            return "—"

    def _profile_status(self, profile_id):
        """Report live browser state without inferring it from metadata."""
        try:
            profile_dir = Path(self.profile_manager.get_profile_dir(profile_id))
            return self._profile_status_from_directory(profile_dir)
        except (AttributeError, OSError, ProfileManagerError, TypeError, ValueError):
            return "Unknown"

    @staticmethod
    def _profile_status_from_directory(profile_dir):
        """Check one cached profile directory without loading profile metadata."""
        try:
            profile_dir = Path(profile_dir)
            if not profile_dir.is_dir():
                return "Missing"
            return "Open" if browser_using_directory(profile_dir) else "Closed"
        except (OSError, TypeError, ValueError, ProfileManagerError):
            return "Unknown"

    def _build_profile_row(self, record):
        profile_id = str(record.get("profile_id", ""))
        display_name = str(record.get("display_name") or profile_id)
        last_opened_at = record.get("last_opened_at")
        try:
            profile_path = Path(self.profile_manager.get_profile_dir(profile_id))
            status = self._profile_status_from_directory(profile_path)
        except (AttributeError, OSError, ProfileManagerError, TypeError, ValueError):
            profile_path = None
            status = "Unknown"
        return {
            "profile_id": profile_id,
            "display_name": display_name,
            "account": self._account_identifier(profile_id),
            "environment": self._display_environment(record),
            "proxy": self._display_proxy(record),
            "status": status,
            "profile_path": str(profile_path) if profile_path is not None else None,
            "last_opened": self._display_last_opened(last_opened_at),
            "created_at": str(record.get("created_at") or ""),
            "last_opened_sort": str(last_opened_at or ""),
        }

    def sort_by_column(self, column):
        """Sort the visible table without changing profile metadata."""
        sort_method = "last_opened" if column == "last_opened" else column
        if self._value(self.sort_method) == sort_method:
            self.sort_reverse = not getattr(self, "sort_reverse", False)
        else:
            if hasattr(self.sort_method, "set"):
                self.sort_method.set(sort_method)
            else:
                self.sort_method = sort_method
            self.sort_reverse = False
        self.apply_search_filter()

    def _cancel_scheduled_callback(self, attribute):
        callback_id = getattr(self, attribute, None)
        if callback_id is None:
            return
        try:
            self.root.after_cancel(callback_id)
        except (AttributeError, RuntimeError, tk.TclError):
            pass
        setattr(self, attribute, None)

    def _schedule_search_filter(self, *_):
        """Debounce typing and filter the current in-memory dataset only."""
        if getattr(self, "_closing", False):
            return
        self._cancel_scheduled_callback("_search_after_id")
        search = str(self._value(getattr(self, "search_var", ""))).strip()
        if not search:
            self.apply_search_filter()
            return
        try:
            self._search_after_id = self.root.after(200, self._run_search_filter)
        except (AttributeError, RuntimeError, tk.TclError):
            self._search_after_id = None

    def _run_search_filter(self):
        self._search_after_id = None
        if not getattr(self, "_closing", False):
            self.apply_search_filter()

    def _sorted_profile_rows(self, rows):
        """Return a sorted view of cached rows without changing the row data."""
        rows = list(rows)
        sort_by = self._value(getattr(self, "sort_method", "name"), "name")
        sort_reverse = bool(getattr(self, "sort_reverse", False))
        if sort_by == "created":
            rows.sort(key=lambda row: row["created_at"], reverse=not sort_reverse)
        elif sort_by == "default_first":
            rows.sort(
                key=lambda row: (
                    row["profile_id"] != "Default",
                    row["display_name"].casefold()
                ),
                reverse=sort_reverse
            )
        else:
            sort_field = sort_by if sort_by in {
                "name", "id", "account", "environment", "proxy", "status", "last_opened"
            } else "name"
            key_field = {"name": "display_name", "id": "profile_id"}.get(
                sort_field, sort_field
            )
            if key_field == "last_opened":
                key_field = "last_opened_sort"
            rows.sort(
                key=lambda row: str(row[key_field]).casefold(),
                reverse=sort_reverse
            )
        return rows

    def _filtered_profile_rows(self):
        search = str(self._value(getattr(self, "search_var", ""))).strip().casefold()
        rows = list(getattr(self, "_profile_rows", []))
        if not search:
            return rows
        return [
            row for row in rows
            if any(search in str(row[field]).casefold() for field in (
                "profile_id", "display_name", "account", "environment",
                "proxy", "status", "last_opened"
            ))
        ]

    def apply_search_filter(self):
        """Apply search and sorting to cached rows without a full refresh."""
        if getattr(self, "_closing", False):
            return
        rows = self._sorted_profile_rows(self._filtered_profile_rows())
        self._render_profile_rows(rows)

    def _render_profile_rows(self, rows):
        selected_ids = set(getattr(self, "selected_profile_ids", set()))
        if hasattr(self, "tree"):
            selected_ids.update(pid for pid, _ in self.get_selected_profiles())
        all_profile_ids = {
            row["profile_id"] for row in getattr(self, "_profile_rows", [])
        }
        if all_profile_ids:
            selected_ids.intersection_update(all_profile_ids)
        visible_ids = {row["profile_id"] for row in rows}
        hidden_selected = selected_ids - visible_ids

        self.table_rows = list(rows)
        self.profiles = [
            (row["profile_id"], row["display_name"])
            for row in rows
        ]
        if not hasattr(self, "tree"):
            return

        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert(
                "",
                "end",
                iid=row["profile_id"],
                values=(
                    row["display_name"],
                    row["account"],
                    row["environment"],
                    row["proxy"],
                    row["status"],
                    row["last_opened"],
                    row["profile_id"],
                )
            )

        visible_selected = [
            row["profile_id"] for row in rows
            if row["profile_id"] in selected_ids
        ]
        if visible_selected:
            self.tree.selection_set(visible_selected)
        self.on_select(None)
        self.selected_profile_ids.update(hidden_selected)

    def _refresh_cached_statuses(self):
        """Update only process status using paths cached by the last full refresh."""
        changed = False
        for row in getattr(self, "_profile_rows", []):
            status = self._profile_status_from_directory(row.get("profile_path"))
            if row.get("status") != status:
                row["status"] = status
                changed = True
        if not changed or not hasattr(self, "tree"):
            return

        visible_rows = {
            row["profile_id"]: row for row in getattr(self, "table_rows", [])
        }
        status_index = PROFILE_TABLE_DATA_COLUMNS.index("status")
        for item in self.tree.get_children():
            row = visible_rows.get(item)
            if row is None:
                continue
            values = list(self.tree.item(item, "values"))
            if len(values) <= status_index:
                continue
            values[status_index] = row["status"]
            self.tree.item(item, values=tuple(values))

    def _poll_status(self):
        self._status_after_id = None
        if getattr(self, "_closing", False):
            return
        try:
            self._refresh_cached_statuses()
        except Exception:
            logger.warning("Profile status polling failed")
        finally:
            self._schedule_status_poll()

    def _schedule_status_poll(self):
        if getattr(self, "_closing", False):
            return
        try:
            self._status_after_id = self.root.after(1500, self._poll_status)
        except (AttributeError, RuntimeError, tk.TclError):
            self._status_after_id = None

    def shutdown(self):
        """Cancel GUI callbacks before the root window is destroyed."""
        self._closing = True
        self._cancel_scheduled_callback("_search_after_id")
        self._cancel_scheduled_callback("_status_after_id")

    def _set_button_state(self, attribute, state):
        button = getattr(self, attribute, None)
        if button is not None:
            button.config(state=state)

    def update_action_buttons(self):
        """Keep primary actions truthful for the current selection."""
        selected_count = len(self.get_selected_profiles()) if hasattr(self, "tree") else 0
        row_count = len(getattr(self, "profiles", []))
        self._set_button_state("btn_open_discord", tk.NORMAL if selected_count else tk.DISABLED)
        self._set_button_state("btn_rename_profile", tk.NORMAL if selected_count == 1 else tk.DISABLED)
        self._set_button_state("btn_edit_profile", tk.NORMAL if selected_count == 1 else tk.DISABLED)
        self._set_button_state("btn_delete_profile", tk.NORMAL if selected_count else tk.DISABLED)
        self._set_button_state("btn_select_all", tk.NORMAL if row_count else tk.DISABLED)
        self._set_button_state("btn_deselect_all", tk.NORMAL if selected_count else tk.DISABLED)

    def edit_profile(self):
        """Open the existing account editor/viewer for the selected profile."""
        profile = self.get_selected_profile()
        if not profile:
            return
        profile_id, _ = profile
        try:
            account = self.account_manager.get_account(profile_id)
            if account:
                self.view_account()
            else:
                self.set_account_for_profile(profile_id)
        except (AttributeError, ProfileManagerError, OSError) as error:
            messagebox.showerror("Error", f"Could not edit profile account:\n{error}")

    def select_all_profiles(self):
        """Select all items in treeview"""
        for item in self.tree.get_children():
            self.tree.selection_add(item)
        self.on_select(None)

    def deselect_all_selection(self):
        """deselect_all all selections"""
        self.tree.selection_remove(self.tree.selection())
        self.selected_profile_ids = set()
        self.on_select(None)

    def get_next_bulk_index(self):
        """Find next 4-digit index based on existing profile names"""
        max_index = 0

        try:
            names = [
                record.get("display_name", "")
                for record in self.profile_manager.get_profile_metadata()
            ]
        except (AttributeError, ProfileManagerError, OSError, TypeError):
            names = [name for _, name in self.profiles]

        for name in names:
            match = re.match(r"^(\d{4}) \|", name)
            if match:
                num = int(match.group(1))
                if num > max_index:
                    max_index = num

        return max_index + 1

    def bulk_import_profiles(self):
        """Import multiple profiles from TXT file"""

        file_path = filedialog.askopenfilename(
            title="Chọn file TXT",
            filetypes=[("Text Files", "*.txt")]
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if not lines:
                messagebox.showwarning("File rỗng", "File TXT không có dữ liệu.")
                return

            start_index = self.get_next_bulk_index()
            current_index = start_index

            created_count = 0

            for line in lines:
                parts = line.split(":")

                if len(parts) < 2:
                    continue  # bỏ dòng sai format

                email = parts[0].strip()
                password = parts[1].strip()
                totp = parts[2].strip() if len(parts) > 2 else ""

                username = email.split("@")[0]
                display_name = f"{current_index:04d} | {username}"

                # Tạo profile
                new_id = self.profile_manager.create_profile(display_name)

                # Chuẩn hoá lại format truyền vào set_account
                if totp:
                    account_string = f"{email}:{password}:{totp}"
                else:
                    account_string = f"{email}:{password}"

                # Set account
                self.account_manager.set_account(new_id, account_string)

                current_index += 1
                created_count += 1

            self.refresh_list()

            messagebox.showinfo(
                "Hoàn tất",
                f"Đã tạo {created_count} profiles.\n"
                f"Bắt đầu từ số {start_index:04d}"
            )

        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể import:\n{e}")

    def update_account_buttons(self):
        """Enable/disable account buttons based on selected profile"""

        if not self.current_profile:
            self._set_button_state("btn_set_account", tk.DISABLED)
            self._set_button_state("btn_view_account", tk.DISABLED)
            self._set_button_state("btn_remove_account", tk.DISABLED)
            return

        pid, _ = self.current_profile
        try:
            account = self.account_manager.get_account(pid)
        except (AttributeError, ProfileManagerError, OSError):
            self._set_button_state("btn_set_account", tk.DISABLED)
            self._set_button_state("btn_view_account", tk.DISABLED)
            self._set_button_state("btn_remove_account", tk.DISABLED)
            return

        if account:
            # Có account
            self._set_button_state("btn_set_account", tk.DISABLED)
            self._set_button_state("btn_view_account", tk.NORMAL)
            self._set_button_state("btn_remove_account", tk.NORMAL)
        else:
            # Chưa có account
            self._set_button_state("btn_set_account", tk.NORMAL)
            self._set_button_state("btn_view_account", tk.DISABLED)
            self._set_button_state("btn_remove_account", tk.DISABLED)

    def on_select(self, event):
        selected = self.get_selected_profiles()
        self.current_profile = selected[0] if len(selected) == 1 else None
        self.selected_profile_ids = {profile_id for profile_id, _ in selected}
        self.update_account_buttons()
        self.update_action_buttons()

    def get_selected_profiles(self):
        """Resolve selection by stable IDs, independently of row labels/icons."""
        names = dict(self.profiles)
        selected = []
        seen = set()
        for item in self.tree.selection():
            values = self.tree.item(item, 'values')
            id_index = getattr(self, "_id_column_index", 1)
            profile_id = values[id_index] if len(values) > id_index else None
            # M1-M4 test doubles and older callers used a two-column table.
            if profile_id not in names and len(values) >= 2:
                profile_id = values[1]
            if profile_id in names and profile_id not in seen:
                selected.append((profile_id, names[profile_id]))
                seen.add(profile_id)
        return selected
    
    def get_selected_profile(self):
        """Get currently selected profile"""
        selection = self.get_selected_profiles()
        if not selection:
            messagebox.showwarning("Chọn profile", "Vui lòng chọn một profile.")
            return None
        
        # For single selection mode in functions that expect one profile
        if len(selection) > 1:
            messagebox.showwarning("Chọn một profile", "Vui lòng chỉ chọn một profile.")
            return None
            
        return selection[0]
    
    def update_status(self, message):
        """Update status bar message"""
        self.status_var.set(message)
        self.root.update_idletasks()
        logger.info(f"Status: {message}")
    
    def refresh_list(self):
        """Reload metadata and rebuild the cached profile display dataset."""
        self.update_status("Loading profiles...")

        try:
            # This is the only path that reloads metadata and builds static row data.
            self._profile_rows = [
                self._build_profile_row(record)
                for record in self.profile_manager.get_profile_metadata()
            ]
            self.apply_search_filter()
            self.update_status(f"Loaded {len(self.profiles)} profiles")
        except Exception as error:
            self._profile_rows = []
            self.profiles = []
            self.table_rows = []
            self.selected_profile_ids = set()
            self.current_profile = None
            if hasattr(self, "tree"):
                for item in self.tree.get_children():
                    self.tree.delete(item)
            self.update_account_buttons()
            self.update_action_buttons()
            logger.error(f"Failed to refresh list: {error}")
            messagebox.showerror("Error", f"Could not load profiles:\n{error}")
            self.update_status("Profile list error")

    def create_profile(self):
        """Create new profile"""
        name = simpledialog.askstring(
            "Tạo Profile Mới",
            "Nhập tên hiển thị (không bắt buộc):",
            parent=self.root
        )
        
        if name is None:  # Cancel
            return
        
        try:
            self.update_status("Đang tạo profile...")
            
            # Create profile
            new_id = self.profile_manager.create_profile(name if name.strip() else None)
            
            # Refresh list
            self.refresh_list()
            if hasattr(self, "tree") and hasattr(self.tree, "exists") and self.tree.exists(new_id):
                self.tree.selection_set(new_id)
                self.on_select(None)
            
            # Ask to set account
            if messagebox.askyesno("Thành công", f"Profile {new_id} đã được tạo.\n\nThiết lập tài khoản Discord ngay?"):
                self.set_account_for_profile(new_id)
            
            self.update_status(f"Đã tạo profile {new_id}")
            
        except Exception as e:
            logger.error(f"Failed to create profile: {e}")
            messagebox.showerror("Lỗi", f"Không thể tạo profile:\n{e}")
            self.update_status("Lỗi tạo profile")
    
    def rename_profile(self):
        """Rename selected profile"""
        profile = self.get_selected_profile()
        if not profile:
            return
        
        pid, name = profile
        
        new_name = simpledialog.askstring(
            "Đổi tên profile",
            "Tên mới:",
            initialvalue=name,
            parent=self.root
        )
        
        if not new_name or not new_name.strip():
            return
        
        try:
            self.update_status(f"Đang đổi tên profile {pid}...")
            self.profile_manager.rename_profile(pid, new_name.strip())
            self.refresh_list()
            self.update_status(f"Đã đổi tên thành {new_name}")
            
        except Exception as e:
            logger.error(f"Failed to rename profile: {e}")
            messagebox.showerror("Lỗi", f"Không thể đổi tên profile:\n{e}")
            self.update_status("Lỗi đổi tên")
    
    def delete_profile(self):
        selected_profiles = self.get_selected_profiles()

        if not selected_profiles:
            messagebox.showwarning("Chọn profile", "Vui lòng chọn profile.")
            return

        confirm = messagebox.askyesno(
            "Xác nhận xóa",
            f"Xóa {len(selected_profiles)} profile?\n\nKhông thể hoàn tác!",
            icon='warning'
        )

        if not confirm:
            return

        deleted = 0
        errors = []

        for pid, name in selected_profiles:
            try:
                self.profile_manager.delete_profile(pid)
                deleted += 1
            except Exception as e:
                logger.error(f"Delete failed {pid}: {e}")
                errors.append(f'{pid}: {e}')

        self.refresh_list()
        self.update_status(f"Đã xóa {deleted} profile")
        if errors:
            messagebox.showwarning('Some profiles could not be deleted', '\n\n'.join(errors[:10]))
    
    def open_discord(self):
        """Open each selected profile separately and report partial failures."""
        selected = self.get_selected_profiles()
        if not selected:
            messagebox.showwarning('Chọn profile', 'Vui lòng chọn profile.')
            return
        requested, running, errors = 0, 0, []
        for pid, name in selected:
            try:
                self.update_status(f"Đang mở Discord với profile {name}...")
                extension_paths = ExtensionManager(self.profile_manager).get_profile_extension_paths(pid)
                if self.launcher.launch_discord(pid, extension_paths or None):
                    requested += 1
                else:
                    running += 1
            except Exception as error:
                logger.error(f'Launch failed for {pid}: {error}')
                errors.append(f'{pid}: {error}')
        # Refresh live process state after launch requests.  Launch failures
        # remain reported even when a status refresh is unavailable.
        if hasattr(self, "tree"):
            try:
                self.refresh_list()
            except Exception:
                pass
        self.update_status(f'Launch requested: {requested}; already running: {running}; failed: {len(errors)}')
        if errors:
            messagebox.showerror('Could not open some profiles', '\n\n'.join(errors[:10]))
    
    def set_account(self):
        """Set account for selected profile"""
        profile = self.get_selected_profile()
        if not profile:
            return
        
        pid, name = profile
        self.set_account_for_profile(pid)

    # ----- NEW dialog box for set account -----
    def show_set_account_dialog(self):
        import re

        def normalize(text):
            """Remove all whitespace and trim."""
            if not text:
                return ""
            return re.sub(r"\s+", "", text.strip())

        dialog = tk.Toplevel(self.root)
        dialog.title("Set Account")
        dialog.geometry("500x380")
        dialog.resizable(False, False)
        dialog.configure(bg="#f5f6fa")
        dialog.grab_set()

        tk.Label(
            dialog,
            text="Thiết lập tài khoản Discord",
            font=("Segoe UI", 13, "bold"),
            bg="#f5f6fa"
        ).pack(pady=(20, 15))

        # =========================
        # PHẦN 1 - Nhập từng field
        # =========================
        form_frame = tk.Frame(dialog, bg="#f5f6fa")
        form_frame.pack(padx=60, fill="x")

        tk.Label(form_frame, text="Email Address",
                font=("Consolas", 10),
                bg="#f5f6fa").pack(anchor="w")
        email_entry = tk.Entry(form_frame, font=("Segoe UI", 10))
        email_entry.pack(fill="x", pady=(0, 10))

        tk.Label(form_frame, text="Password",
                font=("Consolas", 10),
                bg="#f5f6fa").pack(anchor="w")
        pass_entry = tk.Entry(form_frame, font=("Segoe UI", 10), show="*")
        pass_entry.pack(fill="x", pady=(0, 10))

        tk.Label(form_frame, text="2FA CODE (optional):",
                font=("Consolas", 10),
                bg="#f5f6fa").pack(anchor="w")
        totp_entry = tk.Entry(form_frame, font=("Segoe UI", 10))
        totp_entry.pack(fill="x", pady=(10, 20))

        # Divider
        tk.Frame(dialog, height=1, bg="#dcdde1").pack(fill="x", padx=40, pady=10)

        # =========================
        # PHẦN 2 - Nhập raw format
        # =========================
        tk.Label(
            dialog,
            text="HOẶC nhập dưới dạng email:pass:2fa",
            font=("Consolas", 10, "bold"),
            fg="#5865F2",
            bg="#f5f6fa"
        ).pack(pady=(5, 5))

        raw_entry = tk.Entry(dialog, font=("Consolas", 10))
        raw_entry.pack(padx=80, fill="x", pady=(0, 20))

        result = {"value": None}

        def confirm():
            raw_value = raw_entry.get().strip()

            # ======================
            # ƯU TIÊN RAW FORMAT
            # ======================
            if raw_value:
                parts = raw_value.split(":")

                if len(parts) < 2:
                    messagebox.showwarning(
                        "Sai định dạng",
                        "Format phải là email:pass hoặc email:pass:2fa"
                    )
                    return

                email = normalize(parts[0])
                password = normalize(parts[1])
                totp = normalize(parts[2]) if len(parts) > 2 else ""

            else:
                # ======================
                # NHẬP TỪ FIELD
                # ======================
                email = normalize(email_entry.get())
                password = normalize(pass_entry.get())
                totp = normalize(totp_entry.get())

            # ======================
            # VALIDATE BẮT BUỘC
            # ======================
            if not email or not password:
                messagebox.showwarning(
                    "Thiếu thông tin",
                    "mail và pass là bắt buộc."
                )
                return

            # ======================
            # CHUẨN HOÁ 2FA
            # ======================
            if totp:
                totp = totp.upper()  # Discord TOTP không phân biệt hoa thường

            # ======================
            # TẠO KẾT QUẢ
            # ======================
            if totp:
                result["value"] = f"{email}:{password}:{totp}"
            else:
                result["value"] = f"{email}:{password}"

            dialog.destroy()

        tk.Button(
            dialog,
            text="Xác nhận",
            command=confirm,
            bg="#5865F2",
            fg="white",
            activebackground="#4752C4",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            padx=30,
            pady=8,
            cursor="hand2"
        ).pack()

        dialog.wait_window()
        return result["value"]

    # -----Setting Profile's Account -----
    def set_account_for_profile(self, profile_id):
        existing = self.account_manager.get_account(profile_id)
        if existing:
            messagebox.showwarning(
                "Đã có tài khoản",
                "Profile này đã có tài khoản.\n\n"
                "Chỉ có thể View hoặc Remove."
            )
            return
        """Set account for specific profile"""
        account_string = self.show_set_account_dialog()
        
        if not account_string:
            return
        
        try:
            self.update_status(f"Đang cấu hình tài khoản cho {profile_id}...")
            self.account_manager.set_account(profile_id, account_string)
            self.refresh_list()
            self.update_status(f"Đã cấu hình tài khoản cho {profile_id}")
            messagebox.showinfo("Thành công", "Đã cấu hình tài khoản thành công!")
            self.update_account_buttons()

        except InvalidAccountFormatError as e:
            messagebox.showerror("Sai định dạng", str(e))
        except ExtensionError as e:
            messagebox.showerror("Lỗi Extension", 
                               f"Không tìm thấy extension Discord autofill.\n\n"
                               f"Hãy đảm bảo extension tồn tại tại:\n{EXT_DIR}")
        except Exception as e:
            logger.error(f"Failed to set account: {e}")
            messagebox.showerror("Lỗi", f"Không thể cấu hình tài khoản:\n{e}")
            self.update_status("Lỗi cấu hình tài khoản")
            self.update_account_buttons()

    def view_account(self):
        """Open account viewer dialog"""

        profile = self.get_selected_profile()
        if not profile:
            return

        pid, name = profile

        account = self.account_manager.get_account(pid)

        if not account:
            messagebox.showinfo(
                "Chưa có tài khoản",
                "Profile này chưa được cấu hình tài khoản."
            )
            return

        self.show_account_dialog(name, pid, account)

    
    def copy_to_clipboard(self, text):

        if not text:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def show_account_dialog(self, name, pid, account):

        dialog = tk.Toplevel(self.root)
        dialog.title("Account Information")
        dialog.geometry("440x280")
        dialog.resizable(False, False)
        dialog.configure(bg="#f5f6fa")
        dialog.grab_set()

        masked_email = self.account_manager.mask_email(account["email"])
        masked_password = self.account_manager.mask_password(account["password"])
        masked_totp = self.account_manager.mask_totp(account["totp_secret"])

        icon_font = ("Segoe MDL2 Assets", 11)
        text_font = ("Consolas", 10)

        tk.Label(
            dialog,
            text=f"Profile: {name}",
            font=("Segoe UI", 12, "bold"),
            bg="#f5f6fa"
        ).pack(pady=(15, 10))

        frame = tk.Frame(dialog, bg="#f5f6fa")
        frame.pack(fill="both", expand=True, padx=30)

        def create_row(label, masked, real):

            tk.Label(
                frame,
                text=label,
                font=("Consolas", 10, "bold"),
                bg="#f5f6fa"
            ).pack(anchor="w")

            row = tk.Frame(frame, bg="#f5f6fa")
            row.pack(fill="x", pady=(2,10))

            value = tk.StringVar(value=masked)

            value_label = tk.Label(
                row,
                textvariable=value,
                font=text_font,
                bg="#f5f6fa"
            )
            value_label.pack(side="left")

            def toggle():
                if value.get() == masked:
                    value.set(real)
                else:
                    value.set(masked)

            # Show / Hide icon
            # Show / Hide button
            tk.Button(
                row,
                text="\uE722",
                font=icon_font,
                width=3,
                command=toggle,
                relief="raised",
                bd=1,
                bg="#ffffff",
                activebackground="#e6e6e6",
                padx=3,
                pady=1,
                cursor="hand2"
            ).pack(side="left", padx=6)


            # Copy button
            tk.Button(
                row,
                text="\uE8C8",
                font=icon_font,
                width=3,
                command=lambda: self.copy_to_clipboard(real),
                relief="raised",
                bd=1,
                bg="#ffffff",
                activebackground="#e6e6e6",
                padx=3,
                pady=1,
                cursor="hand2"
            ).pack(side="left")

        create_row("Email", masked_email, account["email"])
        create_row("Password", masked_password, account["password"])
        create_row("2FA Secret", masked_totp, account["totp_secret"])

        tk.Button(
            dialog,
            text="Close",
            command=dialog.destroy,
            bg="#5865F2",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=25,
            pady=6
        ).pack(pady=12)
        
    def remove_account(self):
        """Remove account from selected profile"""
        profile = self.get_selected_profile()
        if not profile:
            return
        
        pid, name = profile
        
        confirm = messagebox.askyesno(
            "Xác nhận xóa tài khoản",
            f"Xóa tài khoản Discord khỏi profile '{name}'?",
            icon='question'
        )
        
        if not confirm:
            return
        
        try:
            self.update_status(f"Đang xóa tài khoản khỏi {pid}...")
            self.account_manager.remove_account(pid)
            self.update_status(f"Đã xóa tài khoản khỏi {name}")
            messagebox.showinfo("Thành công", "Đã xóa tài khoản!")
            self.update_account_buttons()
            
        except Exception as e:
            logger.error(f"Failed to remove account: {e}")
            messagebox.showerror("Lỗi", f"Không thể xóa tài khoản:\n{e}")
            self.update_status("Lỗi xóa tài khoản")
            self.update_account_buttons()


# ----------------------------------------------------------------------
# Main Entry Point
# ----------------------------------------------------------------------
def main():
    """Main application entry point"""
    try:
        # Check prerequisites
        if not BROWSER_EXE.is_file():
            error_message = (
                "Chromium browser runtime not found.\n\n"
                f"Expected executable:\n{BROWSER_EXE}\n\n"
                "Keep the complete Ungoogled Chromium runtime in the project's browser folder."
            )
            logger.error(error_message)
            error_root = tk.Tk()
            error_root.withdraw()
            try:
                messagebox.showerror("Browser runtime not found", error_message, parent=error_root)
            finally:
                error_root.destroy()
            return
        
        # Start application
        root = tk.Tk()

        # Keep the legacy registry available for M1-M3 compatibility, but let
        # ProfileManager bootstrap the application-owned profiles.json catalog.
        try:
            state = LocalStateManager()
            with state.operation():
                if not LOCAL_STATE.exists():
                    # A missing legacy registry is safe to initialize when the
                    # legacy data root is empty. Existing legacy files remain
                    # protected by LocalStateManager.load(). Managed profiles
                    # are discovered by ProfileManager below.
                    if PROFILES_JSON.exists():
                        state.save(state._create_default())
                    elif DATA_DIR.exists() and any(path.name != '.manager.lock' for path in DATA_DIR.iterdir()):
                        state.save(state.load())
                    else:
                        state.save(state._create_default())
            ProfileManager().initialize_metadata()
        except ProfileManagerError as error:
            messagebox.showerror('Profile metadata error', str(error), parent=root)
            root.destroy()
            return
        
        # Set icon if available
        try:
            root.iconbitmap(default=BASE_DIR / "icon.ico")
        except:
            pass
        
        app = ProfileManagerApp(root)
        
        # Handle window close
        def on_closing():
            logger.info("Application shutting down")
            app.shutdown()
            root.destroy()
        
        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        print(f"FATAL ERROR: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
