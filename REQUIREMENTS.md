# Discord Profile Manager

## 1. Purpose

Create a Windows desktop application for managing multiple isolated Discord browser profiles through Ungoogled Chromium.

The application should prioritize:

* stability
* simple profile management
* isolated browser sessions
* maintainability
* low setup complexity
* preservation of existing profiles

This is a browser profile manager, not a Chromium fork.

---

# 2. Browser Runtime

Use Ungoogled Chromium directly.

Expected executable:

browser/chrome.exe

Do not depend on Portapps or:

ungoogled-chromium-portable.exe

The complete Chromium runtime stays inside:

browser/

Browser runtime must remain independent from profile data.

---

# 3. Profiles

Each profile must use an independent Chromium user-data directory.

Target structure:

profiles/
├── profile_0001/
├── profile_0002/
├── profile_0003/
└── ...

Profiles must preserve:

* cookies
* sessions
* Local Storage
* IndexedDB
* Discord login state
* browser preferences

Opening one profile must not affect another profile.

---

# 4. Profile Manager Features

Required:

* create profile
* rename profile
* delete profile
* search profile
* sort profiles
* open profile
* open multiple selected profiles
* detect basic profile running state
* bulk profile/account metadata import
* persistent profile metadata

Profile deletion must require deliberate user action.

---

# 5. Application Database

The application should eventually stop using Chromium Local State as its primary application database.

Preferred application-owned metadata:

config/profiles.json

or SQLite if justified later.

Chromium's own files should remain managed by Chromium.

---

# 6. Account Management

Maintain compatibility with the current account workflow during initial migration.

Account management improvements should happen separately after core profile migration is stable.

Sensitive credentials must not appear in logs.

Long-term goal:

use secure Windows credential storage rather than plaintext credential files.

---

# 7. Extensions

Extensions should live under:

extensions/

Avoid unnecessary duplication of identical extension code across hundreds of profiles.

However, do not change existing extension behavior until its current profile-specific configuration mechanism has been understood.

---

# 8. Browser Environment

Every profile may optionally have an environment preset.

Initial presets:

Desktop
Mobile
Custom

Potential properties:

* viewport width
* viewport height
* device scale factor
* language
* timezone
* touch mode
* mobile mode

Environment configuration must be optional.

Default profiles should work without customization.

Deep browser fingerprint spoofing is not part of this project.

---

# 9. Proxy

Every profile may optionally have proxy configuration.

Possible states:

Proxy OFF
Custom Proxy

Profiles must work normally without a proxy.

Proxy configuration must be isolated per profile.

Automatic proxy rotation is not required.

---

# 10. GUI

Keep the application easy to operate without coding knowledge.

Main screen should eventually expose:

* profile name
* account identifier
* profile environment
* proxy state
* running state
* last opened
* search
* multi-selection

Important actions:

Open
Create
Rename
Delete
Edit Profile
Import
Settings

Avoid cluttering the main screen with advanced technical settings.

---

# 11. Browser Runtime Manager

Later milestone.

Features:

* detect installed Chromium version
* detect available browser runtime
* browser path validation
* update support
* update failure recovery
* previous-version rollback

Browser updates must NEVER delete:

profiles/
config/
extensions/
logs/

---

# 12. Logging

Logs should help diagnose application problems.

Logs must not include:

* passwords
* tokens
* TOTP secrets
* sensitive authentication information

---

# 13. Packaging

Final goal:

Windows application executable.

Example distribution:

DiscordProfileManager/
├── Manager.exe
├── browser/
├── profiles/
├── config/
├── extensions/
└── logs/

The application should be portable as a folder where practical.

---

# 14. Development Priorities

Priority order:

1. preserve working legacy behavior
2. migrate away from Portapps
3. stabilize direct Chromium runtime
4. stabilize profile storage
5. create application-owned profile metadata
6. improve GUI
7. add environment presets
8. add optional proxy
9. improve credential security
10. browser runtime updater
11. source-code modularization
12. Windows packaging

Do not implement multiple major milestones simultaneously unless explicitly requested.