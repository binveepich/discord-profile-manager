#!/usr/bin/env python3
"""
Ungoogled Chromium Portable Profile Manager
Professional profile manager for ungoogled-chromium-portable
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

# ----------------------------------------------------------------------
# Configuration and Paths
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LAUNCHER = BASE_DIR / "ungoogled-chromium-portable.exe"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "log"
EXT_DIR = BASE_DIR / "ext" / "discord-autofill-extension"
TOKEN_EXT_DIR = BASE_DIR / "ext" / "discord-token-extractor-extension"
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

# ----------------------------------------------------------------------
# Local State Management
# ----------------------------------------------------------------------
class LocalStateManager:
    """Manage Chromium Local State file operations"""
    
    def __init__(self):
        self.local_state_path = LOCAL_STATE
        
    def load(self):
        """Read and parse Local State JSON file"""
        if not self.local_state_path.exists():
            logger.warning(f"Local State not found at {self.local_state_path}, creating default")
            return self._create_default()
        
        try:
            with open(self.local_state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.debug("Local State loaded successfully")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Local State: {e}")
            # Attempt to recover by creating backup and default
            backup_path = self.local_state_path.with_suffix('.json.bak')
            shutil.copy2(self.local_state_path, backup_path)
            logger.info(f"Corrupted Local State backed up to {backup_path}")
            return self._create_default()
        except Exception as e:
            logger.error(f"Unexpected error loading Local State: {e}")
            return self._create_default()
    
    def save(self, data):
        """Safely write Local State JSON file"""
        try:
            temp_path = self.local_state_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.local_state_path)
            logger.debug("Local State saved successfully")
        except Exception as e:
            logger.error(f"Failed to save Local State: {e}")
            raise ProfileManagerError(f"Cannot save Local State: {e}")
    
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
        pattern = re.compile(r"^Profile (\d+)$")
        max_num = 0
        
        for pid in cache.keys():
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
        logger.info(f"Creating new profile with name: {display_name}")
        
        # Load Local State
        data = self.local_state.load()
        cache = data.setdefault("profile", {}).setdefault("info_cache", {})
        
        # Generate new profile ID
        new_id = self.next_profile_id(cache)
        if display_name is None:
            display_name = new_id
        
        # Add to cache
        cache[new_id] = {
            "name": display_name,
            "avatar_icon": "chrome/theme/IDR_PROFILE_AVATAR_0",
            "created": int(time.time())
        }
        
        # Save Local State
        self.local_state.save(data)
        
        # Initialize profile structure
        self._initialize_profile_structure(new_id)
        
        logger.info(f"Profile {new_id} created successfully")
        return new_id
    
    def _initialize_profile_structure(self, profile_id):
        """Create minimal Chromium profile structure without launching browser"""

        profile_dir = DATA_DIR / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Minimal Preferences file
        prefs_file = profile_dir / "Preferences"

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
        logger.info(f"Renaming profile {profile_id} to {new_name}")
        
        data = self.local_state.load()
        cache = data.get("profile", {}).get("info_cache", {})
        
        if profile_id not in cache:
            raise ProfileNotFoundError(f"Profile {profile_id} not found")
        
        cache[profile_id]["name"] = new_name
        self.local_state.save(data)
        logger.info(f"Profile {profile_id} renamed to {new_name}")
    
    def delete_profile(self, profile_id):
        """Delete a profile and its data"""
        logger.info(f"Deleting profile {profile_id}")
        
        data = self.local_state.load()
        cache = data.get("profile", {}).get("info_cache", {})
        
        if profile_id not in cache:
            raise ProfileNotFoundError(f"Profile {profile_id} not found")
        
        # Remove from cache
        del cache[profile_id]
        self.local_state.save(data)
        
        # Delete profile directory
        profile_dir = DATA_DIR / profile_id
        if profile_dir.exists() and profile_dir.is_dir():
            shutil.rmtree(profile_dir)
            logger.info(f"Deleted profile directory: {profile_dir}")
    
    def get_profile_dir(self, profile_id):
        """Get profile directory path"""
        return DATA_DIR / profile_id

# ----------------------------------------------------------------------
# Extension and Account Management
# ----------------------------------------------------------------------
class AccountManager:
    """Manage Discord account credentials in extension"""
    
    def __init__(self, profile_manager):
        self.profile_manager = profile_manager
    
    def _ensure_both_extensions_installed(self, profile_id):
        """Ensure both extensions are installed in profile"""
        profile_dir = self.profile_manager.get_profile_dir(profile_id)
        
        # Create Extensions folder if not exists
        extensions_dir = profile_dir / "Unpacked Extensions"
        extensions_dir.mkdir(parents=True, exist_ok=True)
        
        installed_exts = []
        
        # Install Discord Autofill Extension
        autofill_target = extensions_dir / "discord-autofill-extension"
        if EXT_DIR.exists():
            if not autofill_target.exists():
                shutil.copytree(EXT_DIR, autofill_target)
                logger.info(f"Autofill extension installed for profile {profile_id}")
            installed_exts.append(autofill_target)
        else:
            raise ExtensionNotFoundError(f"Autofill extension not found at {EXT_DIR}")
        
        # Install Token Extractor Extension
        token_target = extensions_dir / "discord-token-extractor-extension"
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
        return ext_dir / "config.js"
    
    def _ensure_extension_installed(self, profile_id):
        """Ensure extension is installed in profile"""
        profile_dir = self.profile_manager.get_profile_dir(profile_id)
        ext_target = profile_dir / "Unpacked Extensions" / "discord-autofill-extension"
        
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
        profile_dir = self.profile_manager.get_profile_dir(profile_id)
        prefs_file = profile_dir / "Preferences"
        
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
            prefs["extensions"]["ui"] = {"developer_mode": True}
            
            # Write safely
            temp_file = prefs_file.with_suffix('.tmp')
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
        
        config_file = autofill_ext_path / "config.js"
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
        self.launcher_path = LAUNCHER
        
    def launch_discord(self, profile_id, extension_paths=None):
        """Launch Discord with specified profile and multiple extensions"""
        if not self.launcher_path.exists():
            raise ProfileManagerError(f"Launcher not found: {self.launcher_path}")
        
        profile_data_dir = DATA_DIR / profile_id

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
        
        # Add extension arguments if paths provided
        if extension_paths:
            # Filter out None values and convert to strings
            valid_paths = [str(p) for p in extension_paths if p and p.exists()]
            if valid_paths:
                ext_paths_str = ",".join(valid_paths)
                cmd.extend([
                    f"--disable-extensions-except={ext_paths_str}",
                    f"--load-extension={ext_paths_str}"
                ])
        
        logger.info(f"Launching Discord with profile {profile_id} and {len(valid_paths) if extension_paths else 0} extensions")
        
        try:
            subprocess.Popen(
                cmd,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
        except Exception as e:
            logger.error(f"Failed to launch Chromium: {e}")
            raise ProfileManagerError(f"Cannot launch Chromium: {e}")

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
        account = self.account_manager.get_account(pid)

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
        selection = self.tree.selection()
        if selection:
            # Get the first selected item
            item = selection[0]
            item_values = self.tree.item(item, "values")
            # Find matching profile in self.profiles list
            for pid, name in self.profiles:
                if item_values[1] == pid and item_values[0] == f"👤 {name}":
                    self.current_profile = (pid, name)
                    break
        else:
            self.current_profile = None

        self.update_account_buttons()
    
    def get_selected_profile(self):
        """Get currently selected profile"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Chọn profile", "Vui lòng chọn một profile.")
            return None
        
        # For single selection mode in functions that expect one profile
        if len(selection) > 1:
            messagebox.showwarning("Chọn một profile", "Vui lòng chỉ chọn một profile.")
            return None
            
        item = selection[0]
        item_values = self.tree.item(item, "values")
        # Find matching profile
        for pid, name in self.profiles:
            if item_values[1] == pid and item_values[0] == f"👤 {name}":
                return (pid, name)
        return None
    
    def update_status(self, message):
        """Update status bar message"""
        self.status_var.set(message)
        self.root.update_idletasks()
        logger.info(f"Status: {message}")
    
    def refresh_list(self):
        """Refresh profile list with current sorting"""
        self.update_status("Đang tải danh sách profile...")
        
        try:
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
                self.tree.insert("", "end", values=(f"{prefix} {name}", pid))
            
            self.update_status(f"Đã tải {len(self.profiles)} profiles")
            
        except Exception as e:
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
        selections = self.tree.selection()

        if not selections:
            messagebox.showwarning("Chọn profile", "Vui lòng chọn profile.")
            return

        selected_profiles = []
        for item in selections:
            item_values = self.tree.item(item, "values")
            for pid, name in self.profiles:
                if item_values[1] == pid and item_values[0] == f"👤 {name}":
                    selected_profiles.append((pid, name))
                    break

        confirm = messagebox.askyesno(
            "Xác nhận xóa",
            f"Xóa {len(selected_profiles)} profile?\n\nKhông thể hoàn tác!",
            icon='warning'
        )

        if not confirm:
            return

        deleted = 0

        for pid, name in selected_profiles:
            try:
                self.profile_manager.delete_profile(pid)
                deleted += 1
            except Exception as e:
                logger.error(f"Delete failed {pid}: {e}")

        self.refresh_list()
        self.update_status(f"Đã xóa {deleted} profile")
    
    def open_discord(self):
        """Open Discord with selected profile"""
        profile = self.get_selected_profile()
        if not profile:
            return
        
        pid, name = profile
        
        try:
            self.update_status(f"Đang mở Discord với profile {name}...")
            
            # Check and collect both extensions
            profile_dir = self.profile_manager.get_profile_dir(pid)
            extensions_dir = profile_dir / "Unpacked Extensions"
            
            extension_paths = []
            
            # Add autofill extension if exists
            autofill_path = extensions_dir / "discord-autofill-extension"
            if autofill_path.exists():
                extension_paths.append(autofill_path)
            
            # Add token extractor extension if exists
            token_path = extensions_dir / "discord-token-extractor-extension"
            if token_path.exists():
                extension_paths.append(token_path)
            
            # Launch with all found extensions
            self.launcher.launch_discord(pid, extension_paths if extension_paths else None)
            
            self.update_status(f"Discord đã được mở với profile {name}")
            
        except Exception as e:
            logger.error(f"Failed to open Discord: {e}")
            messagebox.showerror("Lỗi", f"Không thể mở Discord:\n{e}")
            self.update_status("Lỗi mở Discord")
    
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
        if not LAUNCHER.exists():
            logger.error(f"Launcher not found: {LAUNCHER}")
            print(f"ERROR: Launcher not found at {LAUNCHER}")
            print("Please ensure this script is in the root directory of ungoogled-chromium-portable.")
            print(f"Current directory: {BASE_DIR}")
            input("\nPress Enter to exit...")
            sys.exit(1)
        
        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create minimal Local State if needed
        if not LOCAL_STATE.exists():
            logger.info("Creating minimal Local State")
            minimal_state = {
                "profile": {
                    "info_cache": {}
                }
            }
            with open(LOCAL_STATE, 'w', encoding='utf-8') as f:
                json.dump(minimal_state, f, indent=2)
        
        # Start application
        root = tk.Tk()
        
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