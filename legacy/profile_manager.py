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
from datetime import datetime
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
# Keep the existing profile data and Local State locations.
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "log"
EXT_DIR = PROJECT_ROOT / "extensions" / "discord-autofill-extension"
TOKEN_EXT_DIR = PROJECT_ROOT / "extensions" / "discord-token-extractor-extension"
LOCAL_STATE = DATA_DIR / "Local State"

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

class ExtensionNotFoundError(ProfileManagerError):
    """Discord autofill extension not found"""
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
        for pid, info in cache.items():
            validate_profile_id(pid)
            if pid.casefold() in seen:
                raise ValueError('Profile IDs refer to the same Windows directory')
            seen.add(pid.casefold())
            if not isinstance(info, dict) or not isinstance(info.get('name', pid), str):
                raise ValueError('Invalid profile entry or name')
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
                if existing:
                    raise ProfileManagerError(f"Profile metadata is missing, but existing data remains at {directory}. Restore Local State before continuing.")
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
# Profile Management
# ----------------------------------------------------------------------
class ProfileManager:
    """Handle profile operations"""
    
    def __init__(self):
        self.local_state = LocalStateManager()
       
    def get_profiles(self):
        """Return list of (profile_id, display_name) sorted by name"""
        data = self.local_state.load()
        cache = data.get("profile", {}).get("info_cache", {})
        
        profiles = []
        for pid, info in cache.items():
            name = info.get("name", pid)
            profiles.append((pid, name))
        
        # Sort alphabetically by display name
        profiles.sort(key=lambda x: x[1].lower())
        
        # Ensure Default is first if exists
        default_profiles = [p for p in profiles if p[0] == "Default"]
        other_profiles = [p for p in profiles if p[0] != "Default"]
        profiles = default_profiles + other_profiles
        
        return profiles
    
    def next_profile_id(self, cache):
        """Generate next profile ID following Profile X pattern"""
        pattern = re.compile(r"^Profile (\d+)$", re.IGNORECASE)
        max_num = 0
        
        # Reserve orphaned directories and files as well as registered IDs.
        for pid in [*cache, *[path.name for path in DATA_DIR.iterdir()]]:
            if pid == "Default":
                continue
            m = pattern.match(pid)
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        
        return f"Profile {max_num + 1}"
    
    def create_profile(self, display_name=None):
        """Create a new profile and initialize it"""
        if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
            raise ProfileManagerError("Profile name must not be empty.")
        with self.local_state.operation():
            self._check_registry_idle()
            data = self.local_state.load()
            cache = data['profile']['info_cache']
            new_id = self.next_profile_id(cache)
            self._initialize_profile_structure(new_id)
            cache[new_id] = {
                'name': display_name.strip() if display_name is not None else new_id,
                'avatar_icon': 'chrome/theme/IDR_PROFILE_AVATAR_0',
                'created': int(time.time()),
            }
            # Publish only after initialization. Failed creations are never reused.
            self.local_state.save(data)
            logger.info(f"Profile {new_id} created successfully")
            return new_id
    
    def _initialize_profile_structure(self, profile_id):
        """Create minimal Chromium profile structure without launching browser"""

        profile_dir = self.get_profile_dir(profile_id)
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
            data = self.local_state.load()
            data['profile']['info_cache'][profile_id]['name'] = new_name.strip()
            self.local_state.save(data)
        logger.info(f"Profile {profile_id} renamed to {new_name}")
    
    def delete_profile(self, profile_id):
        """Delete a profile and its data"""
        with self.local_state.operation():
            self._check_registry_idle()
            data = self.local_state.load()
            cache = data['profile']['info_cache']
            if profile_id not in cache:
                raise ProfileNotFoundError(f"Profile {profile_id} not found")
            profile_dir = self.get_profile_dir(profile_id)
            if browser_using_directory(profile_dir):
                raise ProfileManagerError(f"Close Chromium for {profile_id} before deleting it.")
            pending = None
            if profile_dir.exists():
                if not profile_dir.is_dir():
                    raise ProfileManagerError(f"Profile path is not a directory: {profile_dir}")
                pending = checked_path(DATA_DIR / f'.deleting-{profile_id}-{uuid.uuid4().hex}', DATA_DIR)
                profile_dir.rename(pending)
            else:
                self._check_pending_delete(profile_id)
            del cache[profile_id]
            try:
                self.local_state.save(data)
            except Exception:
                if pending is not None:
                    if profile_dir.exists():
                        raise ProfileManagerError(f"Deletion was interrupted. Profile data is preserved at {pending}; restore it before retrying.")
                    pending.rename(profile_dir)
                raise
            if pending is not None:
                # Resolve and verify the recursive deletion target immediately beforehand.
                checked_path(pending, DATA_DIR)
                try:
                    shutil.rmtree(pending)
                except OSError as error:
                    raise ProfileManagerError(f"Profile was removed from the list, but some data could not be deleted at {pending}. No further cleanup will run automatically.") from error
            logger.info(f"Deleted profile {profile_id}")
    
    def get_profile_dir(self, profile_id):
        """Get profile directory path"""
        return checked_path(DATA_DIR / validate_profile_id(profile_id), DATA_DIR)

    def _check_registry_idle(self):
        if browser_using_directory(DATA_DIR, exact=True):
            raise ProfileManagerError("Chromium is using the shared legacy data directory. Close it before using the manager.")

    def _check_pending_delete(self, profile_id):
        if not DATA_DIR.exists():
            return
        for path in DATA_DIR.iterdir():
            if path.name.startswith(f'.deleting-{profile_id}-'):
                raise ProfileManagerError(f"An interrupted deletion left data at {path}. Restore or inspect that directory before continuing.")

    def require_profile_dir(self, profile_id):
        path = self.get_profile_dir(profile_id)
        if profile_id not in self.local_state.load()['profile']['info_cache']:
            raise ProfileNotFoundError(f"Profile {profile_id} not found. Refresh the list.")
        if not path.is_dir():
            self._check_pending_delete(profile_id)
            raise ProfileNotFoundError(f"Profile directory is missing or invalid: {path}. Restore it before opening; no replacement profile was created.")
        return path

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
class AccountManager:
    """Manage Discord account credentials in extension"""
    
    def __init__(self, profile_manager):
        self.profile_manager = profile_manager
    
    def _ensure_both_extensions_installed(self, profile_id):
        """Ensure both extensions are installed in profile"""
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        
        # Create Extensions folder if not exists
        extensions_dir = checked_path(profile_dir / "Unpacked Extensions", profile_dir)
        extensions_dir.mkdir(parents=True, exist_ok=True)
        
        installed_exts = []
        
        # Install Discord Autofill Extension
        autofill_target = checked_path(extensions_dir / "discord-autofill-extension", profile_dir)
        if EXT_DIR.exists():
            if not autofill_target.exists():
                shutil.copytree(EXT_DIR, autofill_target)
                logger.info(f"Autofill extension installed for profile {profile_id}")
            installed_exts.append(autofill_target)
        else:
            raise ExtensionNotFoundError(f"Autofill extension not found at {EXT_DIR}")
        
        # Install Token Extractor Extension
        token_target = checked_path(extensions_dir / "discord-token-extractor-extension", profile_dir)
        if TOKEN_EXT_DIR.exists():
            if not token_target.exists():
                shutil.copytree(TOKEN_EXT_DIR, token_target)
                logger.info(f"Token extractor extension installed for profile {profile_id}")
            installed_exts.append(token_target)
        else:
            logger.warning(f"Token extractor extension not found at {TOKEN_EXT_DIR}")
            # Không raise error vì extension này không bắt buộc
        
        return installed_exts    
    
    def _get_config_path(self, profile_id):
        """Get path to config.js for profile"""
        profile_dir = self.profile_manager.get_profile_dir(profile_id)
        ext_dir = profile_dir / "Unpacked Extensions" / "discord-autofill-extension"
        return checked_path(ext_dir / "config.js", profile_dir)
    
    def _ensure_extension_installed(self, profile_id):
        """Ensure extension is installed in profile"""
        profile_dir = self.profile_manager.require_profile_dir(profile_id)
        ext_target = checked_path(profile_dir / "Unpacked Extensions" / "discord-autofill-extension", profile_dir)
        
        # Create Extensions folder if not exists
        ext_target.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if source extension exists
        if not EXT_DIR.exists():
            raise ExtensionNotFoundError(f"Extension not found at {EXT_DIR}")
        
        # Copy extension if not already there
        if not ext_target.exists():
            shutil.copytree(EXT_DIR, ext_target)
            logger.info(f"Extension installed for profile {profile_id}")
        
        return ext_target
    
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
        
        # Ensure both extensions are installed
        installed_exts = self._ensure_both_extensions_installed(profile_id)
        
        # Enable developer mode
        self._enable_developer_mode(profile_id)
        
        # Create config.js for autofill extension
        autofill_ext_path = self.profile_manager.get_profile_dir(profile_id) / "Unpacked Extensions" / "discord-autofill-extension"
        config_content = f"""// Discord Auto-fill Extension Configuration
    const ACCOUNT = {{
        email: "{email}",
        password: "{password}",
        totpSecret: "{totp_secret}"
    }};
    """
        
        config_file = self._get_config_path(profile_id)
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        logger.info(f"Account configured for profile {profile_id} with both extensions")
    
    def get_account(self, profile_id):
        """Get account information from config.js"""
        config_file = self._get_config_path(profile_id)
        
        if not config_file.exists():
            return None
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract values using regex
            email_match = re.search(r'email:\s*"([^"]*)"', content)
            password_match = re.search(r'password:\s*"([^"]*)"', content)
            totp_match = re.search(r'totpSecret:\s*"([^"]*)"', content)
            
            if email_match and password_match and totp_match:
                email = email_match.group(1).strip()
                password = password_match.group(1).strip()
                totp = totp_match.group(1).strip()

                # chỉ cần email + password là đủ
                if email and password:
                    return {
                        'email': email,
                        'password': password,
                        'totp_secret': totp  # có thể rỗng
                    }
            
        except Exception as e:
            logger.error(f"Failed to read account for {profile_id}: {e}")
        
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
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(empty_config)
            
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
        self.root.title("Discord Accounts Manager [Based on Ungoogled Chromium]")
        self.root.geometry("700x650")
        self.root.minsize(700, 400)
        self.root.configure(bg='#f0f0f0')
        
        # Initialize managers
        self.profile_manager = ProfileManager()
        self.account_manager = AccountManager(self.profile_manager)
        self.launcher = ChromiumLauncher()
        
        # Variables
        self.profiles = []          # list of (pid, name)
        self.current_profile = None
        self.sort_method = tk.StringVar(value="name") 
        
        # Setup UI
        self.setup_ui()
        
        # Load profiles
        self.refresh_list()
        
        logger.info("Application started")
    
    def setup_ui(self):
        """Setup user interface"""
        # Main container (left + right)
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # ----- LEFT SIDE: Profile list and sorting -----
        left_frame = tk.Frame(main_frame, bg='#f0f0f0')
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Sorting options
        sort_frame = tk.Frame(left_frame, bg='#f0f0f0')
        sort_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(sort_frame, text="Sắp xếp:", bg='#f0f0f0',
                font=('Helvetica', 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        for text, value in [("Tên", "name"), ("ID", "id"), ("Mới nhất", "created"), ("Default đầu", "default_first")]:
            rb = tk.Radiobutton(sort_frame, text=text, variable=self.sort_method,
                                value=value, bg='#f0f0f0',
                                command=self.refresh_list)
            rb.pack(side=tk.LEFT, padx=5)
        
        # Profile treeview with scrollbar
        tree_frame = tk.Frame(left_frame, bg='#f0f0f0')
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create Treeview with scrollbar
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("name", "id"),
            show="headings",  # Hide the default first empty column
            yscrollcommand=scrollbar.set,
            selectmode="extended",  # Enable multi-selection
            height=15
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure scrollbar
        scrollbar.config(command=self.tree.yview)
        
        # Configure columns
        self.tree.heading("name", text="Tên Profile")
        self.tree.heading("id", text="Profile ID")
        
        self.tree.column("name", width=300, anchor="w")
        self.tree.column("id", width=150, anchor="w")
        
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
            tk.Button(
                manager_frame,
                text=text,
                command=cmd,
                bg=bg,
                fg='white',
                activebackground=activebg,
                activeforeground='white',
                **btn_style
            ).pack(pady=3, fill=tk.X)

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
            ("✨ Tạo Profile", self.create_profile, '#0078D7', '#0053A0'),
            ("✏️ Đổi tên", self.rename_profile, '#28A745', '#1E7E34'),
            ("🗑️ Xóa", self.delete_profile, '#DC3545', '#BD2130'),
        ]
        
        for text, cmd, bg, activebg in profile_buttons:
            tk.Button(
                profile_frame,
                text=text,
                command=cmd,
                bg=bg,
                fg='white',
                activebackground=activebg,
                activeforeground='white',
                **btn_style
            ).pack(pady=3, fill=tk.X)
        
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

    def select_all_profiles(self):
        """Select all items in treeview"""
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def deselect_all_selection(self):
        """deselect_all all selections"""
        self.tree.selection_remove(self.tree.selection())

    def get_next_bulk_index(self):
        """Find next 4-digit index based on existing profile names"""
        max_index = 0

        for _, name in self.profiles:
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
            self.btn_set_account.config(state=tk.DISABLED)
            self.btn_view_account.config(state=tk.DISABLED)
            self.btn_remove_account.config(state=tk.DISABLED)
            return

        pid, _ = self.current_profile
        try:
            account = self.account_manager.get_account(pid)
        except (ProfileManagerError, OSError):
            self.btn_set_account.config(state=tk.DISABLED)
            self.btn_view_account.config(state=tk.DISABLED)
            self.btn_remove_account.config(state=tk.DISABLED)
            return

        if account:
            # Có account
            self.btn_set_account.config(state=tk.DISABLED)
            self.btn_view_account.config(state=tk.NORMAL)
            self.btn_remove_account.config(state=tk.NORMAL)
        else:
            # Chưa có account
            self.btn_set_account.config(state=tk.NORMAL)
            self.btn_view_account.config(state=tk.DISABLED)
            self.btn_remove_account.config(state=tk.DISABLED)

    def on_select(self, event):
        selected = self.get_selected_profiles()
        self.current_profile = selected[0] if len(selected) == 1 else None
        self.update_account_buttons()

    def get_selected_profiles(self):
        """Resolve selection by stable IDs, independently of row labels/icons."""
        names = dict(self.profiles)
        selected = []
        seen = set()
        for item in self.tree.selection():
            values = self.tree.item(item, 'values')
            if len(values) >= 2 and values[1] in names and values[1] not in seen:
                selected.append((values[1], names[values[1]]))
                seen.add(values[1])
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
        """Refresh profile list with current sorting"""
        self.update_status("Đang tải danh sách profile...")
        
        try:
            selected_ids = {pid for pid, _ in self.get_selected_profiles()}
            # Load raw data from Local State
            data = self.profile_manager.local_state.load()
            cache = data.get("profile", {}).get("info_cache", {})
            
            # Build list with created timestamp
            raw_profiles = []
            for pid, info in cache.items():
                name = info.get("name", pid)
                created = info.get("created", 0)
                raw_profiles.append((pid, name, created))
            
            # Sort according to selected method
            sort_by = self.sort_method.get()
            if sort_by == "name":
                raw_profiles.sort(key=lambda x: x[1].lower())
            elif sort_by == "id":
                raw_profiles.sort(key=lambda x: x[0])
            elif sort_by == "created":
                raw_profiles.sort(key=lambda x: x[2], reverse=True)
            elif sort_by == "default_first":
                default = [p for p in raw_profiles if p[0] == "Default"]
                others = [p for p in raw_profiles if p[0] != "Default"]
                others.sort(key=lambda x: x[1].lower())
                raw_profiles = default + others
            
            # Store only (pid, name) for later use
            self.profiles = [(p[0], p[1]) for p in raw_profiles]
            
            # deselect_all treeview and repopulate
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            for pid, name in self.profiles:
                prefix = "⭐" if pid == "Default" else "👤"
                self.tree.insert("", "end", iid=pid, values=(f"{prefix} {name}", pid))

            self.tree.selection_set([pid for pid, _ in self.profiles if pid in selected_ids])
            self.on_select(None)
            
            self.update_status(f"Đã tải {len(self.profiles)} profiles")
            
        except Exception as e:
            self.profiles = []
            self.current_profile = None
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.update_account_buttons()
            logger.error(f"Failed to refresh list: {e}")
            messagebox.showerror("Lỗi", f"Không thể tải profiles:\n{e}")
            self.update_status("Lỗi tải danh sách")
    
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
                profile_dir = self.profile_manager.get_profile_dir(pid)
                extensions_dir = profile_dir / 'Unpacked Extensions'
                extension_paths = [extensions_dir / name for name in
                                   ('discord-autofill-extension', 'discord-token-extractor-extension')
                                   if (extensions_dir / name).exists()]
                if self.launcher.launch_discord(pid, extension_paths or None):
                    requested += 1
                else:
                    running += 1
            except Exception as error:
                logger.error(f'Launch failed for {pid}: {error}')
                errors.append(f'{pid}: {error}')
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
            self.update_status(f"Đã cấu hình tài khoản cho {profile_id}")
            messagebox.showinfo("Thành công", "Đã cấu hình tài khoản thành công!")
            self.update_account_buttons()

        except InvalidAccountFormatError as e:
            messagebox.showerror("Sai định dạng", str(e))
        except ExtensionNotFoundError as e:
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
        
        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Start application
        root = tk.Tk()

        # Initialize only a genuinely fresh registry; never reset existing data.
        try:
            state = LocalStateManager()
            with state.operation():
                if not LOCAL_STATE.exists():
                    state.save(state.load())
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
