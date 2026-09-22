# Discord Profile Manager — Safe Parallel Refactor Handoff

Inspection snapshot: 2026-09-15, Windows, repository `I:\Discord_Profile_Manager`.

This document records the current source tree after the committed M8–M11 work and
defines a safe plan for an additive `revamped/` implementation. It is an inspection
artifact, not an implementation plan that authorizes changing the default entrypoint.
No application code, tests, Git history, browser runtime, credentials, configuration,
or profile data was modified for this inspection. The only file created by this task
is this document.

Where a conclusion is not directly established by source or tests, it is marked
`INFERRED` or `UNKNOWN`.

## 1. Current Git State

### Snapshot

- Current branch: `main`.
- HEAD: `9a92bb9f679591fbbddb2fd7b1239a4e829d3658` (`M11: add source app manual acceptance checklist`).
- Upstream relationship: `main...origin/main [ahead 4]`; `origin/main` is at M7.
- Tracked-file diff: clean (`git diff --quiet` passed).
- Overall working tree: not clean because untracked files are present.
- `revamped/` does not currently exist.

At the beginning of the inspection, the existing untracked items were:

```text
AGENTS_APPEND_PACKAGING_LOCK.md
CODEX_HANDOFF.md
OVERNIGHT_PROMPT.txt
QUICK_START.txt
README_SOURCE_WORKFLOW_PATCH.md
codex_autonomous_flow.zip
docs/autonomous/
sendtstogpt.zip
```

These files were preserved and their ownership was not inferred. `REFACTOR_HANDOFF.md`
is added by this task and will itself appear as an additional untracked file after
this document is created.

Therefore, “clean” has two meanings here: the tracked source tree is clean, but the
Git working tree is not clean. No reset, clean, checkout, commit, or history rewrite
was performed.

### Last eight relevant commits

The eight commits from M4 through M11 are the relevant recent history:

| Commit | Date | Subject | Refactor-relevant result |
| --- | --- | --- | --- |
| `a7a1c28` | 2026-09-14 | M4: add application-owned profile metadata catalog | Added `config/profiles.json`, bootstrap/reconciliation, metadata validation, and atomic catalog writes while retaining the legacy registry. |
| `689fab4` | 2026-09-14 | M5: improve isolated extension deployment | Added validated reusable extension discovery, staged per-profile deployment, profile-local configuration preservation, and extension/account tests. |
| `ea05448` | 2026-09-14 | M6: improve responsive profile manager GUI | Added the cached table model, search/sort behavior, multi-selection, live status polling, and responsive/scrollable action panel. |
| `24f7716` | 2026-09-14 | M7: add per-profile browser environment presets | Added Desktop/Mobile/Custom normalization, persistence, editor state, and environment launch arguments. |
| `f3bb779` | 2026-09-15 | M8: close optional proxy milestone | Added unauthenticated per-profile proxy normalization, parsing, persistence, launch switches, UI, and safety tests. |
| `86ec73c` | 2026-09-15 | M9: add stable source entrypoint | Added the root `main.py` wrapper and documented source-run behavior. |
| `2d948d2` | 2026-09-15 | M10: add safe source verification workflow | Added `scripts/verify.py`, syntax/runtime structure checks, and an embedded unit-test gate. |
| `9a92bb9` | 2026-09-15 | M11: add source app manual acceptance checklist | Added the current manual acceptance document and separated automated, smoke, GUI, and Discord evidence. |

`CODEX_HANDOFF.md` and `CODEX_STATUS.md` are untracked historical notes. Their
opening status text predates the M8 commit and must not be treated as the current
Git snapshot without reconciling it against this document and `git log`.

## 2. Current Verification Baseline

The two mandated commands were run from `I:\Discord_Profile_Manager` exactly as
requested. No destructive manual tests were run, and the optional real-Chromium
smoke test was not run.

### Safe verification script

Command:

```powershell
python -B scripts/verify.py
```

Observed output:

```text
SYNTAX: PASS
UNIT TESTS: PASS
ENTRYPOINT: PASS
RUNTIME STRUCTURE: PASS
AUTONOMOUS GATE: PASS
```

Exit code: `0`.

`scripts/verify.py` compiles `main.py`, `legacy/profile_manager.py`, the top-level
test modules, and itself; runs the full unit discovery command with output hidden;
checks that `main.py` still delegates to legacy; and checks only that
`browser/chrome.exe` exists as a file. It does not start Chromium or inspect raw
profile/config/log data.

### Full verbose unit suite

Command:

```powershell
python -B -m unittest discover -s tests -v
```

Observed terminal summary:

```text
----------------------------------------------------------------------
Ran 170 tests in 8.912s

OK
```

Exit code: `0`. All 170 discovered tests reported `ok`; the verbose run showed no
failure or error. The test modules are M1 through M8 (`test_m1_runtime.py` through
`test_m8_proxy.py`). `tests/browser_smoke_m2.py` is an opt-in diagnostic script and
is not discovered because its filename does not begin with `test`.

The tests construct disposable workspaces under ignored `tmp/` paths, patch the
legacy module’s path constants, mock `subprocess.Popen` and `psutil.process_iter`,
and mock GUI dialogs/Tk objects. Based on that test design, the baseline run did not
need to touch the real profile roots or launch the bundled runtime. The post-run
tracked diff remained clean.

### Evidence that is still absent

- No visible GUI startup or interaction has been manually verified in this task.
- No real-Chromium smoke result was collected.
- No real Discord login, account autofill, or TOTP behavior was tested.
- No packaging, installer, updater, or runtime replacement was attempted.

## 3. Current Entry Points

### `main.py`

`main.py` is a seven-line stable wrapper:

```python
from legacy.profile_manager import main

if __name__ == "__main__":
    main()
```

Running `python -B main.py` imports `legacy.profile_manager`, then calls its
`main()` only when the wrapper is executed as a script. The wrapper does not add a
new application layer and does not currently import `revamped`.

Important consequence: importing the wrapper imports the legacy module and therefore
triggers legacy import-time logging setup before `main()` is called.

### `legacy/profile_manager.py`

Running `python -B .\legacy\profile_manager.py` executes the same module’s bottom
`if __name__ == "__main__": main()` guard. This is the frozen reference behavior
that must remain runnable throughout the parallel refactor.

### Control flow

```text
python -B main.py
    -> import legacy.profile_manager
        -> resolve paths from __file__
        -> create legacy/log if needed
        -> construct a dated FileHandler and configure logging
    -> legacy.main()
        -> verify browser/chrome.exe is a file
        -> create Tk root
        -> initialize/validate legacy compatibility state and profiles.json
        -> construct ProfileManagerApp
        -> build GUI, load cached profile rows, start status polling
        -> enter Tk mainloop
```

The direct legacy command follows the same flow after module execution. Browser
launch happens later from a user action in `ProfileManagerApp.open_discord()`; it is
not an import-time action.

### Import-time and startup side effects

Import-time effects in the legacy module are:

1. `BASE_DIR` and all path constants are resolved from `__file__`, not the current
   working directory.
2. `LOG_DIR.mkdir(parents=True, exist_ok=True)` creates `legacy/log` if needed.
3. A dated log path is created and `logging.basicConfig(...)` is evaluated with a
   `FileHandler` and `StreamHandler`. The handler construction can open/create a
   log file before any GUI is shown.
4. A module-level `logger` is obtained.

There is no import-time GUI creation, Chromium launch, profile scan, account read,
or browser process detection. The test loader explicitly patches `Path.mkdir`,
`logging.FileHandler`, and `logging.basicConfig` to suppress those import-time
effects.

Startup-time effects in `main()` include a runtime file check, Tk root creation,
manager-lock acquisition, possible initialization of the legacy `Local State`,
metadata bootstrap/reconciliation, GUI construction, and the Tk event loop. An
optional `icon.ico` is attempted and silently ignored if unavailable.

## 4. Complete Legacy Component Map

Line references below refer to the current `legacy/profile_manager.py` at the
inspection snapshot. The proposed destinations are targets for `revamped/`; no such
files have been created yet.

### 4.1 Global configuration, constants, and mutable state

| Item | Architectural responsibility and dependencies | Callers and side effects | Tests covering it | Proposed destination |
| --- | --- | --- | --- | --- |
| `BASE_DIR`, `PROJECT_ROOT` (`34–35`) | Establish a script-relative project root. They depend on `Path(__file__)` and are the basis for every runtime path. | Read by all path consumers and the launcher/startup code. No filesystem write by themselves. | `test_m1_runtime.test_paths_do_not_depend_on_working_directory`, Unicode/space path test. | `revamped/core.py` path configuration, preferably as an injected `ProjectPaths` value rather than module globals. |
| `BROWSER_EXE` (`36`) | Points to the required direct runtime `browser/chrome.exe`; it deliberately excludes the old Portapps executable. | Read by `main()` and `ChromiumLauncher.launch_discord()`. Used in error messages and subprocess command construction. | M1 missing-runtime, directory-named-runtime, launch-argument, and entrypoint tests; verification structure check. | `core.py`/`launcher.py`, injected into the launcher and startup composition. |
| `CONFIG_DIR`, `PROFILES_JSON` (`38–39`) | Identify the application-owned catalog. `profiles.json` is the primary post-M4 catalog and is not a Chromium-owned file. | Read/written by `ProfileMetadataManager` and used by bootstrap. Tests patch them to disposable roots. | All M4 metadata tests; M7/M8 persistence tests. | `storage.py` with a `ProfileCatalogStore` and injected paths. |
| `DATA_DIR`, `LOCAL_STATE` (`41`, `48`) | Identify the pre-M4 legacy registry and legacy profile roots. `Local State` remains a compatibility reader/mirror. | Read/written by `LocalStateManager`, bootstrap, migration, and mirror publication. This is the highest-risk compatibility boundary. | M1/M2 lifecycle, M3 migration, M4 bootstrap, M7/M8 restart tests. | `storage.py` legacy adapter; never combine its schema with the application catalog. |
| `PROFILES_DIR` (`42`) | Identifies managed isolated Chromium user-data roots for new and migrated profiles. | Used by discovery, ID allocation, metadata path serialization, migration, and deletion. | M2/M3/M4 lifecycle and containment tests. | `core.py` path policy plus `profiles.py` lifecycle service. |
| `LOG_DIR`, `log_file`, `logger` (`43`, `92–101`) | Define the legacy log location and shared logger. | Import-time directory/file setup; nearly every manager logs operational status/errors. Log messages intentionally omit account values, but legacy account storage itself remains plaintext. | M1 import loader suppresses setup; M5/M8 inspect logger calls for secret hygiene. | `core.py` logger factory called from `revamped.main`, with no production import-time handler creation. |
| `EXTENSIONS_DIR`, `AUTOFILL_EXTENSION_NAME`, `EXT_DIR`, `PROFILE_EXTENSIONS_DIR_NAME` (`44–47`) | Define reusable extension source and per-profile unpacked deployment location/name. | Read by `ExtensionManager` and account/GUI workflows; extension deployment writes under a selected profile only. | M1/M5 extension and account tests; M8 UI source checks. | `extensions.py` with an injected `ExtensionPaths`/source policy. |
| `NEW_PROFILE_PATTERN`, `MANAGER_PATH_KEY`, `METADATA_VERSION` (`50–52`) | Encode managed ID allocation, the legacy migration marker, and application catalog schema version. | Used by validation, ID allocation, legacy mirror conversion, catalog validation, and migration. | M2/M3/M4 tests. | `models.py`/`storage.py` schema constants. |
| Environment constants (`DEFAULT_ENVIRONMENT_PRESET`, `ENVIRONMENT_DESKTOP`, `ENVIRONMENT_MOBILE`, `ENVIRONMENT_CUSTOM`, `SUPPORTED_ENVIRONMENT_PRESETS`, `MOBILE_ENVIRONMENT_DEFAULTS`, `LOCALE_PATTERN`) (`55–82`) | Define the M7 vocabulary, desktop compatibility alias, mobile defaults, and locale syntax. | Read by normalization, editor state, launch-argument construction, GUI, and tests. `MOBILE_ENVIRONMENT_DEFAULTS` is a mutable module-level dict. | M7 and M8 environment tests, including default/mobile/custom parity and no-spoofing checks. | `environment.py`; return copies of defaults and inject clock/config only where needed. |
| Proxy constants (`SUPPORTED_PROXY_SCHEMES`, `PROXY_HOST_LABEL_PATTERN`, `PROXY_HOST_PATTERN`) (`64–71`) | Define the narrow M8 unauthenticated endpoint grammar. | Read by proxy normalization/parser/UI; no network access. | M8 parser, normalization, persistence, IPv6, invalid-input, and secret-boundary tests. | `proxy.py`. |
| `PROFILE_TABLE_COLUMNS`, `PROFILE_TABLE_DATA_COLUMNS` (`83–86`) | Define the GUI’s display columns and hidden stable-ID column. | Read by `setup_ui`, row rendering, selection, status updates, and tests. | M6/M7/M8 GUI tests. | `gui.py` or `models.py` view constants, with stable IDs kept separate from labels. |

The important mutable module global is `MOBILE_ENVIRONMENT_DEFAULTS`; it is a
configuration dict and callers must not mutate it in place. `logger` is a mutable
logging handle, but it is not application profile state. Manager instance state
(`_loaded_bytes`, `_legacy_mirror_enabled`, `_unpublished_paths`, `_processes`, GUI
selection/callback fields) is covered below as instance state rather than global
state.

### 4.2 Exception classes

All exceptions are declared at lines `106–132` and are public test seams even though
they contain no additional logic.

| Class | Responsibility and dependencies | Callers/side effects | Tests | Proposed destination |
| --- | --- | --- | --- | --- |
| `ProfileManagerError` | Base application error for validation, storage, lifecycle, launch, and GUI-facing failures. | Raised throughout the module and caught by GUI/startup boundaries. | Broad M1–M8 error assertions. | `core.py` or `errors.py` inside `revamped` if a separate error file is justified. |
| `ProfileNotFoundError` | Distinguishes unknown/unregistered/missing profile records from generic failures. | Raised by catalog/profile operations and account/launcher prerequisites. | M2/M3/M4/M7/M8 missing-profile tests. | `core.py`; preserve subclass relationship. |
| `ExtensionError` | Base extension discovery/deployment error. | Caught by account setup and optional launch extension discovery. | M5 extension tests and GUI account error path. | `core.py`; preserve semantic category. |
| `ExtensionNotFoundError` | Reports absent reusable source during account setup. | Prevents account setup from creating a partial deployment. | M5 missing-source test. | `core.py`. |
| `ExtensionDeploymentError` | Reports unsafe/failed staged deployment. | Preserves old deployment/config through staging rollback. | M5 deployment-failure tests. | `core.py`. |
| `InvalidAccountFormatError` | Reports missing required account fields. | Caught by account dialog workflow. | M1 account workflow and GUI path. | `core.py`. |
| `ProxyValidationError` | Reports invalid or credential-bearing proxy input. | Rejected before catalog write; parser may return credential fields only transiently so UI can explain the M8 boundary. | M8 parser/invalid/secret tests. | `core.py` plus `proxy.py` raises. |

### 4.3 Top-level safety and process helpers

| Function | Responsibility, dependencies, callers, and side effects | Tests | Proposed destination |
| --- | --- | --- | --- |
| `validate_profile_id` (`135–143`) | Rejects empty/trimmed/path-like/Windows-reserved/dot/deleting IDs. Depends on `PureWindowsPath`; raises `ProfileManagerError`. Called by both stores, profile resolution, migration, and browser layout validation. No write. | M2 path-alias and malformed metadata tests; indirectly most lifecycle tests. | `core.py` path/identity policy. |
| `checked_path` (`146–162`) | Enforces lexical containment, checks every existing path component for symlinks/reparse points, and verifies resolved containment. Depends on `Path`, `stat`; raises before unsafe use. Called by storage, profile lifecycle, extension, and launcher. | M2 junction/containment/extension-path tests; M3 migration and M5 extension safety tests. | `core.py`; make root policy explicit and test it independently. |
| `validate_manager_path` (`165–169`) | Validates the legacy `manager_path` marker against `profile_####`; prevents arbitrary legacy registry paths. | M2/M3 malformed marker and ID allocation tests. | `core.py` or `models.py` migration-marker validation. |
| `validate_candidate_profile_name` (`172–178`) | Boolean wrapper used while scanning roots; ignores unsafe candidates instead of aborting a scan. | M2/M3/M4 discovery and orphan tests. | `core.py`/`profiles.py`. |
| `ensure_tree_has_no_links` (`181–190`) | Rejects symlinks/reparse points anywhere in a tree before copy/deployment. Depends on `checked_path` and `os.walk`. | M3 migration and M5 extension deployment safety tests. | `core.py` filesystem safety helper. |
| `browser_using_directory` (`193–234`) | Detects live Chromium processes by normalized `--user-data-dir`, including separate-argument syntax, relative paths, parent fallback after renderer `AccessDenied`, and process errors. Depends on `psutil`, `Path`, and the application error type. It has no write but can block destructive actions or launch. | M2 running/renamed/restarted/sandboxed/uninspectable/exited/shared-root tests; M6–M8 status tests. | `processes.py`, behind an injectable process inspector. |

### 4.4 `LocalStateManager` (`239–378`)

This is the compatibility store for the Chromium-shaped legacy registry, not the
future primary application database.

- `__init__` binds `LOCAL_STATE` and an optimistic-concurrency byte snapshot
  (`_loaded_bytes`).
- `operation` creates/checks `legacy/data/.manager.lock` and acquires a non-blocking
  OS lock (`msvcrt` on Windows, `fcntl` elsewhere). It serializes manager mutations
  and launches and raises a user-facing error when another operation is active.
- `_validate` enforces the legacy `profile.info_cache` shape, valid IDs, case-folded
  ID uniqueness, valid names, unique `manager_path` values, and safe nonnegative
  creation timestamps.
- `_unique_keys` rejects duplicate JSON object keys.
- `load` reads UTF-8/UTF-8-BOM JSON, preserves malformed/unreadable files by raising,
  and refuses to invent a default registry when physical data remains. Missing
  metadata is only treated as a default when both legacy and managed roots are empty.
- `save` validates, checks the loaded byte snapshot, writes a flushed/fsynced
  temporary file, atomically replaces the registry, and cleans temporary files.
- `_create_default` returns the minimal Chromium-shaped object.

Dependencies: `LOCAL_STATE`, `DATA_DIR`, `PROFILES_DIR`, `PROJECT_ROOT`,
`checked_path`, validators, JSON, temporary files, OS locking, and `logger`.
Callers: `ProfileManager`, `main()`, and tests directly. Side effects are lock-file
creation, registry reads/writes, and logging; it must never touch Chromium-owned
files inside a profile. Tests: M1 runtime, M2 safety/lifecycle, and M3 migration.

Proposed destination: `revamped/storage.py` as `LegacyStateStore` plus an injected
`OperationLock`. Preserve its schema and recovery semantics in a compatibility
adapter; do not let new catalog code depend directly on the old dictionary shape.

### 4.5 Timestamp, environment, proxy, and serialized-path helpers (`384–885`)

| Function/group | Responsibility and dependencies | Callers/side effects/tests | Proposed destination |
| --- | --- | --- | --- |
| `utc_timestamp`, `timestamp_from_epoch` (`384–397`) | Produce UTC ISO timestamps and convert legacy numeric seconds with safe fallback. Depend on `datetime`, `timezone`, and `math`. | `ProfileManager` record creation/mirror conversion/open tracking; M1/M4/M7/M8 persistence tests. Time is the main nondeterministic input. | `models.py`; inject a clock for deterministic tests. |
| `normalize_environment_preset` (`399–410`) | Maps `default`/`desktop`/`mobile`/`custom` aliases to safe preset values, defaulting to desktop. | `effective_environment`, setters/editor; M7/M8 tests. Pure. | `environment.py`. |
| `normalize_locale` (`413–430`) | Validates and canonicalizes locale separators/casing. | Environment normalization and launch args; M7 tests. Pure. | `environment.py`. |
| `normalize_timezone` (`433–449`) | Validates an IANA timezone through `ZoneInfo`; deliberately does not create a launch switch. | Environment normalization/editor; M7 test explicitly checks persistence without fake launch. Pure except timezone database lookup. | `environment.py`. |
| Proxy normalization group: `normalize_proxy_scheme`, `normalize_proxy_host`, `normalize_proxy_port`, `_proxy_off_state`, `normalize_proxy_config` (`452–525`) | Sanitizes scheme, DNS/IP/IPv6 host, port, full endpoint, and disabled state. Rejects credentials/path syntax and returns no partial enabled config. | `ProfileManager.set_proxy`, `effective_proxy`, parser/launcher/UI; M8 tests. Pure. | `proxy.py`. |
| `effective_proxy`, `proxy_launch_arguments` (`528–555`) | Non-mutating safe effective state and one optional `--proxy-server=scheme://host:port` switch; brackets IPv6 only at assembly. | Launcher, GUI display, M8 tests. No network. | `proxy.py`. |
| `_parse_proxy_host_port`, `parse_proxy_string` (`558–688`) | Parses supported provider-like strings, including IPv6 and credential-bearing forms. Credentials are returned transiently so UI can reject them; they are not accepted by `set_proxy`. | Proxy dialog and M8 parser tests. Do not log or persist returned secret fields. | `proxy.py`, with a clearly documented transient parse result. |
| Environment normalization group: `normalize_viewport_dimension`, `normalize_scale_factor`, `normalize_environment_config` (`691–763`) | Bounds dimensions/scale, validates locale/timezone, and accepts only supported boolean mobile/touch fields and aliases. | `effective_environment`, `set_environment`, editor; M7/M8 tests. Pure. | `environment.py`. |
| `effective_environment`, `environment_editor_state`, `environment_launch_arguments` (`766–852`) | Resolve safe Desktop/Mobile/Custom behavior, provide dialog state, and construct generic Chromium switches. Mobile forces mobile/touch; Desktop produces no overrides; timezone is stored only. | Profile manager, launcher, GUI, M7/M8 tests. No browser/process/network side effects. | `environment.py`. |
| `metadata_path_for_profile`, `profile_path_from_metadata` (`855–884`) | Serialize/resolve only `profiles/` and `legacy/data/` relative paths with containment and traversal protection. | Metadata validation, profile resolution, migration, mirror; M3/M4/M5 tests. Filesystem checks but no writes. | `core.py` path policy plus `storage.py` serialization. |

### 4.6 `ProfileMetadataManager` (`887–1029`)

This class owns the versioned application catalog at `config/profiles.json`.

- `_forbidden_fragments` and `_validate_field_names` reject sensitive key names
  (password/token/TOTP/cookie/session/proxy-credential/extension-secret-like forms)
  recursively while allowing unknown non-sensitive application fields.
- `_validate_timestamp` requires timezone-bearing ISO timestamps where required.
- `_validate` enforces version `1`, a list of records, required identity/path/time/
  proxy-state fields, unique case-folded IDs and directory mappings, and safe paths.
  Environment/proxy values are intentionally loadable when malformed so optional
  launch configuration falls back safely.
- `_unique_keys` rejects duplicate JSON keys.
- `load` treats missing/zero-byte files as uninitialized, otherwise validates the
  original bytes without repairing or overwriting invalid content.
- `save` performs validation, optimistic byte comparison, temporary JSON write,
  flush/fsync, re-parse/re-validate, atomic replacement, and cleanup.

Dependencies: metadata paths, validators, timestamps, JSON, `tempfile`, `os`, and
`logger`. Callers: `ProfileManager` and M4/M7/M8 tests. Side effects are limited to
the application catalog file and temporary files. Proposed destination:
`revamped/storage.py` as `ProfileCatalogStore`, with record validation/model
conversion kept separate from legacy-state compatibility.

### 4.7 `ProfileManager` (`1034–1771`)

`ProfileManager` is currently both a catalog service and the profile filesystem
lifecycle service. That combination is the largest extraction seam.

| Responsibility group | Important methods | Dependencies/callers/side effects | Tests | Proposed destination |
| --- | --- | --- | --- | --- |
| Construction and catalog shape | `__init__`, `_empty_catalog`, `_record`, `_record_map` | Constructs `LocalStateManager` and `ProfileMetadataManager`; tracks `_legacy_mirror_enabled` and `_unpublished_paths`. Record creation uses relative path serialization and defaults environment to legacy `default` plus proxy off. | M1–M8 setup helpers and persistence tests. | `profiles.py` service plus `models.py` record factory. |
| Bootstrap/discovery | `_legacy_record`, `_looks_like_profile_directory`, `_scan_profile_root`, `_read_legacy_catalog_for_bootstrap`, `_bootstrap_catalog`, `_reconcile_managed_profiles`, `_reconcile_legacy_profiles`, `_load_catalog`, `initialize_metadata` | Reads old registry only for bootstrap/reconciliation, scans physically recognizable roots, preserves old mappings, imports orphaned managed roots, and writes the new catalog. It may create the compatibility registry when safe. | M2 missing/corrupt registry tests; M3 migration; M4 bootstrap/reconciliation/recovery. | `storage.py` bootstrap coordinator plus `profiles.py` discovery. |
| Metadata-facing APIs | `get_profile_metadata`, `get_environment`, `set_environment`, `get_proxy`, `set_proxy` | Validate ID, lock, require physical profile for mutation, normalize optional settings, publish catalog and optional mirror. Environment/proxy failures must not make a profile unlaunchable. | M4, M7, M8 persistence/isolation/malformed-value tests. | `profiles.py` service methods over typed records and stores. |
| Legacy mirror publication | `_legacy_info_for_record`, `_sync_legacy_registry`, `_restore_legacy_registry`, `_save_catalog` | Keeps M1–M3 `Local State` compatible when mirror is active, publishes mirror then catalog, restores original mirror if catalog publication fails. This is a coupled two-file transaction without a true database transaction. | M1/M2/M3 mirror preservation/failure tests; M4 compatibility tests. | `storage.py` `LegacyMirror`/publication coordinator. |
| Listing and ID allocation | `get_profiles`, `next_profile_id` | Sorts display names with exact-`Default` priority and allocates collision-free `profile_####` IDs from catalog, both roots, and pending deletions. | M1/M2/M3/M4 tests. | `profiles.py` plus `models.py` sorting/ID policy. |
| Create/initialize | `create_profile`, `_initialize_profile_structure` | Under lock, allocates an ID, creates `Default/Preferences` and `Unpacked Extensions`, then publishes metadata. A failed publish leaves the initialized directory and records it in `_unpublished_paths`; IDs are never reused. | M1/M2/M3/M4 creation/failure tests. | `profiles.py`; filesystem creation behind an injected filesystem service. |
| Rename/delete | `rename_profile`, `delete_profile`, `_check_pending_delete` | Rename changes display metadata only and is allowed while running. Delete checks live process state, stages the directory as `.deleting-<id>-UUID`, publishes catalog removal, then recursively deletes; failure restores or reports staging and never auto-cleans it. | M1/M2/M3/M4 delete/rename/running/interrupted/failure tests. | `profiles.py` with a dedicated destructive-operation policy. |
| Resolution and requirements | `get_profile_dir`, `_resolve_profile_dir`, `_check_registry_idle`, `require_profile_dir` | Resolves registered managed or legacy roots, preserves a narrow read-only fallback for empty setups, blocks unknown/missing profiles and shared registry roots, checks pending deletions. | M2/M3/M4 missing-path, path-safety, shared-root tests. | `profiles.py` over `core.py` path policy. |
| Migration | `migrate_profile` | Explicit copy-only legacy-to-managed migration. Rejects links, running source, missing/non-directory source, collision; copies without removing legacy source; publishes marker/catalog only after copy; leaves both copies if metadata publication fails. | Entire M3 suite and M4 migrated-profile test. | `profiles.py` migration operation with explicit transaction/rollback result. |
| Open bookkeeping/layout validation | `mark_profile_opened`, `_mark_profile_opened`, `get_browser_profile_dir` | Records successful launch time, validates independent Chromium user-data layout, rejects flat shared-root data, malformed browser Local State, invalid last-used directory, and links. | M1/M2/M3/M4/M7/M8 launch and timestamp tests. | `profiles.py`/`launcher.py` with `BrowserProfileLayout` validator. |
| `_terminate_process_tree` | Legacy helper to terminate a process tree; not used by the current launcher path. | Depends on `psutil`; catches/logs errors. Caller UNKNOWN in current source search; it appears to be retained legacy code. | No direct current unit test found. | `processes.py` only if a future explicit close feature needs it; otherwise leave out of first extraction. |

The manager’s side effects include lock acquisition, catalog/legacy registry writes,
profile directory creation/rename/delete/copy, and logging. It must not overwrite
Chromium profile internals during metadata operations, and migration must remain
copy-only.

### 4.8 `ExtensionManager` (`1776–1990`)

`ExtensionManager` validates and deploys the single supported unpacked extension.
It depends on a `ProfileManager` for safe profile resolution, `EXT_DIR`, path/link
safety helpers, JSON, `shutil`, `os.walk`, and UUID staging names.

- `_source_root`, `_profile_extensions_dir`, `_declared_file`, and
  `_validate_extension_directory` form the source/deployment validation layer:
  manifest v3, `config.js`, declared content scripts/icons, file existence, and no
  linked paths.
- `get_source_path`, `discover_sources` expose reusable source discovery.
- `profile_extension_path` resolves one profile’s deployment location.
- `get_profile_extension_paths` returns an existing valid deployment or `[]`; an
  invalid optional deployment is logged and skipped so it cannot block browser use.
- `_remove_path` performs validated cleanup of staged/backup paths.
- `ensure_profile_extension` stages a source copy, preserves existing profile
  `config.js` and unknown profile-local files, validates the stage, swaps it into
  place, and restores the old deployment on failure.

Tests: M1 extension arguments/account workflow and all M5 extension tests. Proposed
destination: `revamped/extensions.py`, with `ExtensionSourceValidator` and
`ProfileExtensionDeployer` kept in one module. The deployer should receive a safe
profile-directory capability rather than reaching through a broad manager object.

### 4.9 `AccountManager` (`1991–2211`)

`AccountManager` is the legacy compatibility boundary for account data. It depends
on `ProfileManager`, constructs an `ExtensionManager`, reads/writes profile-local
extension `config.js`, edits Chromium `Preferences` to enable developer mode, and
uses regex/JSON parsing.

- `_ensure_extension_installed` and `_ensure_both_extensions_installed` preserve
  the current one-extension behavior and the old compatibility method name.
- `_get_config_path` resolves profile-local `config.js` through safe paths.
- `_enable_developer_mode` refuses a running profile, reads the browser profile’s
  `Preferences`, sets `extensions.ui.developer_mode`, and replaces the file.
- `set_account` accepts `email:password[:2faSecret]`, removes whitespace, uppercases
  TOTP, deploys the extension, enables developer mode, and atomically writes a
  profile-local JavaScript config. This is plaintext legacy storage and is not the
  long-term security design.
- `get_account` parses the three expected fields and returns plaintext values to
  callers. It avoids logging config contents.
- `remove_account` replaces the config with empty values rather than deleting the
  file.
- `mask_email`, `mask_password`, and `mask_totp` are display-only transformations.

Tests: M1 account/storage/import tests, M2 missing-profile protection, M5 isolated
configuration/restart/deployment/log-hygiene tests, and M6 GUI account-flow tests.
Proposed destination: `revamped/accounts.py`, but no new credential-storage design
should be invented during parity work. Keep a clearly isolated compatibility
adapter and require a human checkpoint before changing storage or touching live
profile data.

### 4.10 `ChromiumLauncher` (`2216–2287`)

The launcher depends on `BROWSER_EXE`, `subprocess`, `ProfileManager`, environment
and proxy argument builders, extension path validation, process detection, and
logging. It keeps `_processes` as an in-memory map keyed by profile ID.

`launch_discord` performs these operations in this order:

1. Check that the browser runtime is a file; this preserves the M1 error ordering.
2. Construct a fresh `ProfileManager`, acquire the operation lock, check shared
   roots, load the catalog, require the registered profile, and get its record.
3. Return `False` if the manager’s remembered process is still alive or live
   process detection says the profile is already open.
4. Validate the independent Chromium profile layout.
5. Build the command: executable, `--user-data-dir`, existing fixed flags, then
   environment switches, proxy switches, the Discord URL, and optional extension
   switches.
6. Call `subprocess.Popen` with `shell=False`, stdout/stderr suppressed, and
   `CREATE_NO_WINDOW` on Windows. An immediately nonzero process is an error.
7. Remember the process, update `last_opened_at`, and return `True`.

Tests: M1 launch/runtime/extension tests; M2 process, repeat-open, path, and failure
tests; M3 managed-root tests; M7 environment and M8 proxy argument tests. Proposed
destination: `revamped/launcher.py`. The fresh manager construction is an implicit
dependency to remove by dependency injection, but the external behavior and lock
ordering must remain covered during the transition.

### 4.11 `ProfileManagerApp` (`2292–4090`)

This class combines Tk widget construction, a cached view model, selection rules,
dialogs, user confirmation, lifecycle orchestration, account UI, environment UI,
proxy UI, and error presentation.

| GUI responsibility | Important methods/fields | Dependencies and side effects | Tests | Proposed destination |
| --- | --- | --- | --- | --- |
| Composition and widgets | `__init__`, `setup_ui`; `root`, `tree`, button attributes, Tk variables | Constructs `ProfileManager`, `AccountManager`, `ChromiumLauncher`; creates all widgets, binds events, and schedules polling. | M1 startup mocks; M6/M7/M8 source/UI assertions. | `gui.py`, with a thin controller constructed by `revamped.main`. |
| Sidebar scroll behavior | `_sidebar_pointer_inside`, `_scroll_sidebar_by`, `_on_sidebar_mousewheel` | Routes wheel events only when the pointer is over the sidebar. | M6/M7 GUI source/behavior tests. | `gui.py`. |
| Safe display/model helpers | `_value`, `_display_environment`, `_display_proxy`, `_display_last_opened`, `_account_identifier`, `_profile_status`, `_profile_status_from_directory`, `_build_profile_row` | Produces table-safe row data, uses only account email as identifier, omits password/TOTP/proxy secrets, and probes live status. | M6/M7/M8 display/status/secret tests. | `gui.py` or a small view-model section in `models.py`; keep pure display methods separate from Tk. |
| Search/sort/render/cache | `sort_by_column`, `_cancel_scheduled_callback`, `_schedule_search_filter`, `_run_search_filter`, `_sorted_profile_rows`, `_filtered_profile_rows`, `apply_search_filter`, `_render_profile_rows`, `_refresh_cached_statuses`, `_poll_status`, `_schedule_status_poll`, `shutdown` | Search/sort operate on cached rows; status polling only changes status; callbacks are debounced/cancelled; rendering uses hidden stable IDs. | M6/M7/M8 fake-tree/fake-variable tests. | `gui.py`, with a pure `ProfileTableModel` extracted first. |
| Button/selection state | `_set_button_state`, `update_action_buttons`, `update_account_buttons`, `on_select`, `get_selected_profiles`, `get_selected_profile`, `select_all_profiles`, `deselect_all_selection` | Enforces single-selection account/environment/proxy/rename actions and multi-selection open/delete. Stable ID is taken from the hidden ID column, with a two-column compatibility fallback. | M2/M6 selection/button tests. | `gui.py` controller/view-model. |
| Profile list/actions | `refresh_list`, `create_profile`, `rename_profile`, `delete_profile`, `open_discord` | Presents dialogs/confirmations, invokes services, handles partial multi-open failures, refreshes cached rows, and writes user-facing status/log messages. | M1/M2/M6 GUI workflow tests. | `gui.py`; service calls should be narrow and injectable. |
| Environment/proxy dialogs | `edit_environment`, `edit_proxy` and their nested callbacks | Builds safe edit forms, preserves preset state, rejects authenticated proxy save, calls profile setters, and refreshes the table. | M7/M8 source and fake-state tests; manual acceptance still required. | `gui.py`, perhaps with small dialog helpers only if needed. |
| Account dialogs/import | `bulk_import_profiles`, `set_account`, `show_set_account_dialog`, `set_account_for_profile`, `view_account`, `show_account_dialog`, `remove_account`, `copy_to_clipboard`, `edit_profile` | Imports synthetic TXT accounts, displays/masks/explicitly reveals credentials, copies values to clipboard only by user action, and calls legacy account workflow. | M1/M5/M6 account/import tests. | `gui.py`; do not broaden account access while extracting. |

### 4.12 `main()` (`4095–4163`)

`main()` is the composition/startup boundary. It checks the browser runtime,
creates Tk, initializes the legacy registry and application catalog under the lock,
handles metadata errors, attempts the icon, creates `ProfileManagerApp`, registers
window shutdown, and enters `mainloop`. Its outer exception handler logs a critical
error, prints a fatal message, waits for console input, and exits nonzero.

Tests: M1/M2 startup and missing-runtime tests; `scripts/verify.py` checks that the
root wrapper still delegates. Proposed destination: `revamped/main.py` for the new
composition root. Keep `main.py` pointed at legacy until the explicit migration
gates in sections 13 and 14 are satisfied.

## 5. Dependency Map

### Major runtime graph

```text
main.py
  -> legacy.profile_manager.main
       -> LocalStateManager                (lock + legacy registry bootstrap)
       -> ProfileManager.initialize_metadata
            -> LocalStateManager
            -> ProfileMetadataManager      (profiles.json)
            -> path/link/ID helpers
       -> ProfileManagerApp
            -> ProfileManager              (catalog + lifecycle)
            -> AccountManager              (extension config/account workflow)
                 -> ExtensionManager       (profile-local extension deployment)
                      -> ProfileManager
            -> ChromiumLauncher            (browser command/process state)
                 -> new ProfileManager     (implicit duplicate service instance)
                 -> browser_using_directory
                 -> environment helpers
                 -> proxy helpers
                 -> extension path checks
                 -> subprocess.Popen
```

### Component dependencies

| Component | Direct dependencies | Filesystem/process side effects |
| --- | --- | --- |
| GUI | Tkinter, messagebox/simpledialog/filedialog, `ProfileManager`, `AccountManager`, `ChromiumLauncher`, display/environment/proxy helpers, logger | Creates widgets, reads user-selected import files, invokes profile/account/extension/launch operations, updates clipboard/status, schedules polling. |
| `ProfileManager` | `LocalStateManager`, `ProfileMetadataManager`, validators/path serializers, environment/proxy helpers, `browser_using_directory`, `shutil`, `datetime`, logger | Creates/renames/copies/deletes profile directories, writes catalog and optional legacy mirror, acquires locks. |
| `ProfileMetadataManager` | JSON, `PROFILES_JSON`, timestamps/path validators, temp files, logger | Atomic `config/profiles.json` replacement only. |
| `LocalStateManager` | JSON, `LOCAL_STATE`, `DATA_DIR`, path validators, OS locking, temp files, logger | Reads/writes legacy `Local State` and creates `.manager.lock`; must not modify Chromium internal state in a user-data root. |
| `ChromiumLauncher` | `subprocess`, `psutil` via process helper, fresh `ProfileManager`, environment/proxy/extension helpers, runtime path | Starts Chromium with per-profile user-data root; updates launch timestamp. |
| `ExtensionManager` | `ProfileManager`, extension source constants, `checked_path`, `ensure_tree_has_no_links`, JSON, `shutil`, UUID | Reads/validates source; stages, swaps, preserves, and cleans per-profile extension deployment. |
| `AccountManager` | `ProfileManager`, `ExtensionManager`, JSON/regex, profile `Preferences`, logger | Reads/writes profile-local `config.js`; writes developer-mode preference; returns plaintext values to the legacy UI. |
| Environment helpers | `math`, regex, `ZoneInfo`, immutable constants plus the mobile-default dict | Pure normalization/argument generation; timezone database lookup only. |
| Proxy helpers | `ipaddress`, regex, proxy constants | Pure parser/normalizer/argument generation; explicitly no network access. |
| Path/validation helpers | `Path`, `PureWindowsPath`, `stat`, `os.walk`, `ipaddress` where relevant | Read-only checks; block unsafe or linked paths. |
| Logging | Python logging, legacy log path | Import-time directory/file setup; operational messages. Secret hygiene depends on call sites. |
| Filesystem operations | `pathlib`, `open`, `tempfile`, `shutil`, `os` | Metadata atomics, profile create/rename/delete/migration, extension/config deployment. |
| Process detection | `psutil`, `Path` | Read-only live process inspection; can block mutation/launch. |

### Circular and implicit dependencies

1. `AccountManager` owns an `ExtensionManager`, while both receive the same
   `ProfileManager`. This is a manageable object graph but makes the account service
   responsible for extension composition.
2. `ChromiumLauncher.launch_discord()` constructs a *new* `ProfileManager` instead
   of accepting the GUI’s manager. That is an implicit consistency boundary and
   makes tests rely on shared module globals rather than shared service state.
3. `ProfileManager._save_catalog()` publishes the legacy mirror before the new
   catalog and attempts a compensating restore. The two stores therefore have an
   implicit transaction relationship.
4. The GUI directly calls helpers such as `effective_environment`, `effective_proxy`,
   and `browser_using_directory`, so presentation code is coupled to policy and
   process inspection.
5. `main()` separately prepares `Local State` and then asks `ProfileManager` to
   bootstrap metadata. This duplicate startup orchestration is intentional legacy
   behavior but should become one explicit composition step in `revamped`.
6. Module globals are the dependency-injection mechanism for tests: changing a
   constant after object construction changes what later instances use. A refactor
   that replaces these with immutable imported settings without an adapter will
   break the current test strategy.

## 6. Test Seam Map

The current tests do not import `legacy.profile_manager` normally. They execute the
source into a synthetic module and patch module-level objects. These seams are
critical compatibility constraints.

| Seam | Tests depending on it | Refactor breakage risk | Compatibility adapter needed? |
| --- | --- | --- | --- |
| `tests/test_m1_runtime.py:load_manager()` dynamically executes the canonical source with a configurable `module.__file__` | Every M1–M8 test imports `test_m1_runtime` and reuses its loader. | A normal import, a renamed module, or a new path model can bypass the loader’s temporary-root isolation or change `BASE_DIR`/`PROJECT_ROOT` expectations. | Yes for legacy tests: keep a frozen legacy loader. New compatibility tests should load legacy in a subprocess/module adapter and load revamped through explicit injected paths. |
| Import-time `Path.mkdir`, `logging.FileHandler`, `logging.basicConfig` patches | `load_manager()` in M1 and all derived suites. | Moving logging setup can make tests create real legacy logs; preserving import-time setup in revamped would reproduce an unwanted side effect. | Yes on the legacy side only; revamped should configure logging from its composition root and expose a testable logger factory. |
| Module path globals: `DATA_DIR`, `PROFILES_DIR`, `CONFIG_DIR`, `PROFILES_JSON`, `LOCAL_STATE`, `BROWSER_EXE`, `EXT_DIR` | M1 `setUp`; M3 path tests; M4/M5/M7/M8 persistence tests; M6 GUI fixture. | Objects may read different roots if paths are captured too early or if only `PROJECT_ROOT` is patched. A refactor that hardcodes project paths can touch real data. | Yes. Define a `TestWorkspace`/`ProjectPaths` adapter and keep the legacy module-global patching path available. |
| Module `subprocess.Popen` | M1 launch tests, M2 repeat/open/failure tests, M3, M5, M7, M8. | Direct process creation would launch Chromium or make command assertions nondeterministic. | Yes. Inject a process factory in revamped; legacy adapter patches its module import. |
| Module `psutil.process_iter` and `manager.psutil` exceptions | M1 setup; M2 running, sandboxed, uninspectable, exited, shared-root tests; M6–M8 status tests. | A process service with different exception translation or process-name handling can allow unsafe deletion or incorrectly mark profiles running. | Yes. Use a fake `ProcessInspector` with equivalent `AccessDenied`, `NoSuchProcess`, and generic-error cases. |
| `browser_using_directory` | M2 lifecycle; M6 status; M7 status; M8 “search/status do not probe proxy”. | If GUI polling starts loading metadata/proxy or changes call order, the tests and product behavior regress. | Yes. Keep a narrow process detector seam and separate status polling from metadata loading. |
| `Path.read_bytes`, `Path.lstat`, `Path.rename`, `Path.replace` | M2 unreadable metadata, junction, delete rename, atomic replace; M4 atomic catalog failure. | Replacing `Path` operations with a different filesystem abstraction can remove failure coverage or change rollback semantics. | Yes. Contract tests should inject filesystem faults; legacy tests continue patching the old class. |
| Module `shutil.copytree` and `shutil.rmtree` | M2 delete cleanup; M3 migration copy failure; M5 deployment failure. | Broad exception wrapping, early cleanup, or changed staging order could delete/lose source data or hide partial destinations. | Yes. Add fault-injectable filesystem operations and assert source/staging invariants. |
| `profiles.local_state.save`, `profiles._initialize_profile_structure` | M2 failed initialization/create publication, metadata-failure paths; M3 metadata failure. | Refactoring private calls without preserving failure ordering can publish markers/catalog entries too early or reuse IDs. | Adapter not required for new production code, but compatibility tests must model these fault points and legacy tests must remain untouched. |
| `ProfileManager` private fields/methods: `local_state`, `metadata`, `_record_map`, `_resolve_profile_dir`, `require_profile_dir`, `_initialize_profile_structure`, `migrate_profile` | M1 setup; M2/M3/M4 tests; M5 account/extension setup; M7/M8 persistence. | Existing tests and callers rely on these as accessible seams despite their underscore names. Hiding them abruptly will break the frozen suite. | Yes for any temporary dual-backend adapter; do not promise private-name parity as the long-term API. |
| `ProfileManagerApp.__new__` plus manually populated attributes | M1/M2/M5/M6/M7/M8 GUI tests and smoke script. | A GUI class that requires a fully initialized Tk root or different attributes cannot be exercised headlessly. | Yes. Keep a pure `ProfileTableModel` and a controller whose dependencies can be supplied without `__init__`; retain a legacy GUI adapter until parity. |
| `FakeVar` (`get`/`set`) and `FakeTree` (`get_children`, `insert`, `delete`, `selection`, `selection_set`, `selection_add`, `selection_remove`, `item`) | M6, M7, M8 headless GUI tests. | Changing selection/render protocols, row value ordering, or callback timing breaks tests and can corrupt stable-ID selection. | Yes. Treat the fake protocols as a documented view contract; add an adapter for real Tk widgets. |
| Tk module objects: `tk.Tk`, `messagebox`, `simpledialog`, `filedialog`, `tk` constants/widgets | M1/M2 startup/dialog tests, M1/M5 import tests, M6 create/error tests. | Real dialogs or Tk initialization in tests would be unsafe/headless; moving imports changes patch targets. | Yes. Inject dialog and UI services in revamped; keep legacy module patch targets unchanged. |
| `ProfileManagerApp.setup_ui` and `edit_proxy` source text inspected with `inspect.getsource` | M7 and M8 source assertions. | A refactor that moves UI out of the legacy class will fail these legacy tests even if the UI is behaviorally equivalent. | Keep legacy class frozen. New tests should assert behavior through injected widgets, not source text. |
| Public module names/constants/classes: `ProfileManagerError`, all manager classes, `main`, `PROFILE_TABLE_*`, `MOBILE_ENVIRONMENT_DEFAULTS`, environment/proxy parser and launch functions | Directly referenced across the M1–M8 suites. | Renaming or changing return shapes creates broad breakage and makes side-by-side comparison difficult. | Provide explicit legacy and revamped adapters; do not use `from revamped import *` as a compatibility shortcut. |
| `logger` mock and `logger.mock_calls` | M5 and M8 secret-hygiene tests. | Logging account/proxy values or changing message interpolation can leak secrets or fail hygiene checks. | Yes. Use a logger interface with redaction tests and preserve legacy logger patchability. |
| `SOURCE` and `PROJECT_ROOT` in tests; test discovery conventions | M1 loader and all imported test modules; `scripts/verify.py`. | Moving tests or renaming `browser_smoke_m2.py` could change the 170-test baseline and verification behavior. | Keep existing tests frozen; add `tests/compatibility/` without changing discovery semantics until separately approved. |

The test suite also directly inspects return shapes: profile lists are tuples of
`(profile_id, display_name)`, metadata is a list of mutable-looking dict copies,
proxy effective state has `enabled/scheme/host/port`, environment state has a
`preset` plus normalized fields, and launch arguments are ordered lists. These
shapes are compatibility contracts until a new adapter deliberately translates
them.

## 7. Behavioral Contracts

The following separates user-visible/persistence behavior from implementation
details that tests currently observe. Revamped must preserve the pure and safety
contracts before any default-entrypoint change.

### 7.1 Pure or deterministic contracts

| Area | Contract to preserve |
| --- | --- |
| Profile identity/path validation | Reject Windows path aliases, traversal, reserved names, invalid managed markers, case-colliding IDs, links/junctions, and profile paths outside the two managed roots. A rejection must happen before the relevant write/delete/launch. |
| Environment normalization | `default` and `desktop` mean normal desktop behavior; `mobile` yields fixed generic mobile/touch behavior with 390×844 and scale 1.0 defaults; `custom` accepts only bounded viewport, scale, locale, timezone, mobile, and touch values; malformed optional values safely fall back to desktop-compatible behavior. No deep fingerprint spoofing. |
| Proxy normalization | Proxy is off by default; valid unauthenticated HTTP/HTTPS/SOCKS4/SOCKS5 host/port values normalize deterministically; IPv6 is bracketed only in the launch argument; invalid or partial enabled metadata behaves as off. No network calls, rotation, health checks, provider integration, or authentication storage. |
| Proxy parser boundary | Credential-bearing strings may be parsed transiently so the UI can explain the boundary, but credentials must not be saved, logged, or passed to Chromium; Save must reject them. Error text must not echo the secret. |
| Metadata transformations | Catalog records contain stable IDs, display names, relative allowed paths, timezone-bearing timestamps, optional environment data, and proxy-off default. Unknown non-sensitive application fields survive legacy registry operations where the legacy contract requires it. Sensitive field names are rejected from `profiles.json`. |
| Launch argument generation | Desktop preserves the established fixed command and no environment/proxy switches. Environment switches precede proxy switches; Discord URL remains present; extension switches preserve the current two-switch joined-path shape and ordering. `shell=False` is required. |
| GUI view model | Search and sort are display-only over cached rows; account table output contains only a safe identifier; stable selection follows hidden profile IDs rather than names/icons; status polling updates live status without reloading metadata or probing proxy. |
| Masking/formatting | Email, password, and TOTP display masking remains the default in the account dialog; explicit reveal/copy remains an intentional user action in the legacy workflow. |

### 7.2 Stateful and safety contracts

| Area | Contract to preserve |
| --- | --- |
| Profile creation | Allocate a collision-free managed `profile_####`; create `Default/Preferences` and optional extension directory; publish metadata only after structure creation; never reuse an unregistered failed-create directory. |
| Profile rename | Change display metadata only; never rename physical Chromium data; allow rename while the browser is running; survive manager restart. |
| Profile delete | Require deliberate GUI confirmation; refuse while the profile is running or process state is uninspectable; stage directory before catalog removal; restore on publication failure; report and preserve staging on cleanup failure; never auto-clean interrupted deletion on restart. |
| Profile migration | Explicit and copy-only from legacy to managed root; reject links, collisions, missing/non-directory/running sources; leave legacy source untouched on success and every failure; publish marker/catalog only after copy succeeds. |
| Metadata recovery | Missing/empty metadata may bootstrap only when physical state is safe; malformed/unreadable metadata is left unchanged and reported; missing directories remain metadata entries and are not recreated; managed orphans can be reconciled safely; atomic writes preserve the original on failure and reject stale byte snapshots. |
| Legacy compatibility storage | Existing M1–M3 `legacy/data/Local State` shape remains readable and is mirrored only when active; Chromium-owned Local State files inside profile roots must not be used as the application catalog or rewritten by catalog operations. |
| Process detection | Detect browser processes after manager restart, accept `--user-data-dir=value` and separated argument forms, resolve relative paths, handle renderer access denial via a readable browser parent, and fail closed when inspection is impossible. |
| Browser launch | Use `browser/chrome.exe`, one isolated user-data root per profile, existing fixed flags, safe environment/proxy/extension switches, no shell, suppressed child output, and successful last-opened bookkeeping. Missing runtime and unknown/missing profile errors must occur in the established order. |
| Extension deployment | Validate manifest v3/config/declared files and reject links; stage replacement; preserve profile-local `config.js` and unknown extra files; keep deployments isolated per profile; skip invalid optional deployments during launch but report source/deployment errors during account setup. |
| Account workflow | Preserve `email:password[:totp]` compatibility, one profile-local config per account, developer-mode behavior, restart persistence, import naming, and masking. Do not place credentials in `profiles.json` or logs. Real secure-storage migration is a separate human-reviewed milestone. |
| GUI selection/state | Existing profiles load on startup; multi-open continues after one failure; single-profile actions are disabled for multi-selection; refresh preserves selected IDs; canceling delete leaves data; status polling stops cleanly on shutdown. |
| Error handling | User-facing failures should identify the operation/path without exposing password, token, TOTP, cookie, session, or proxy credentials. Failure paths must preserve source/metadata according to the operation’s rollback contract. |

### 7.3 Implementation details observed by tests, but not desirable as new design

These should be preserved through adapters while the current suite is frozen, but
revamped should not copy them unnecessarily:

- all production behavior in one 4,163-line file;
- module-global path constants as dependency injection;
- import-time log directory/file setup;
- the legacy Chromium-shaped registry as a mirror;
- `ChromiumLauncher` constructing a new `ProfileManager` internally;
- direct GUI access to manager internals and module helper functions;
- exact private method names and `inspect.getsource` assertions;
- exact temporary filename prefixes and internal staging field names, unless the
  safety semantics depend on them.

## 8. Refactor Risk Classification

### LOW RISK

- Pure timestamp formatting once a clock is injected and fallback behavior is
  covered.
- Pure environment normalization and launch-switch generation.
- Pure proxy normalization/parser/launch-switch generation, provided credentials
  remain transient and never enter logs/files.
- Pure GUI display formatting and table sorting/filtering.
- Data classes/record conversion that do not write files or resolve live paths.

These are deterministic and can be extracted behind side-by-side tests, although
proxy and path inputs still require security-focused cases.

### MEDIUM RISK

- `ProfileMetadataManager` catalog validation and atomic persistence.
- Managed/legacy profile discovery and reconciliation.
- Headless GUI controller/table model and selection state.
- Read-only browser layout validation.
- Public error/return-shape adapters.

These components own persistent schemas or cross-component contracts, but can be
tested with disposable roots and fault injection without starting Chromium.

### HIGH RISK

- `LocalStateManager` locking, legacy registry preservation, and mirror publication.
- `ProfileManager` create, rename, migration, deletion staging, and ID allocation.
- `browser_using_directory` and launcher process ordering.
- `ExtensionManager` staged deployment and preservation of profile-local files.
- GUI dialogs that orchestrate destructive actions or account configuration.
- Any change to launch argument order, profile layout interpretation, or missing-data
  recovery.

These operations can alter user data, block or permit concurrent Chromium use, or
make an otherwise existing profile unlaunchable.

### CRITICAL

- Account credential storage/read/reveal/migration.
- Any operation against real `profiles/`, `legacy/data/`, `config/profiles.json`,
  extension deployments, or the browser runtime.
- Changing `main.py` to use revamped before automated parity, manual acceptance,
  rollback, and explicit user approval.
- Deletion/recovery code that could select a path outside the intended root.
- Packaging, runtime replacement, updater/rollback, installer, or release work.

These areas require a human checkpoint and must remain outside unattended overnight
changes. The existing plaintext account workflow is a compatibility liability, but
changing it during structural refactoring would be more dangerous than isolating it.

## 9. Recommended Extraction Order

Each stage below is additive. The legacy implementation remains the executable
reference until the completion gates pass. “Rollback” means stop using the new
stage, leave legacy files/data untouched, and remove/revert only the additive
revamped change in its own branch/commit; no profile data rollback should be
attempted automatically.

| Stage | Source behavior and proposed destination | Required compatibility tests | Acceptance criteria | Rollback strategy |
| --- | --- | --- | --- | --- |
| 1. Baseline/freeze | Record the M11 baseline, freeze `legacy/profile_manager.py`, and define adapters without changing runtime behavior. | Existing `verify.py` plus full 170-test suite; record Git status and file hashes without reading profile contents. | Baseline remains `170/170`, verify passes, no legacy diff, no default switch. | Delete/abandon additive branch only; legacy remains runnable. |
| 2. Pure validation/path policy | Extract `validate_profile_id`, `validate_manager_path`, `validate_candidate_profile_name`, `checked_path`, `ensure_tree_has_no_links`, and serialized path helpers into `revamped/core.py`. | M2 path aliases/junctions, M3 containment/migration, M4 directory mapping, M5 extension path tests. Add deterministic contract cases for relative/absolute/traversal/link paths. | Legacy and revamped return/raise equivalent results for synthetic paths; no real path is resolved for mutation. | Launcher/profile services continue calling legacy helpers or adapter; do not change `main.py`. |
| 3. Environment normalization | Move timestamp-independent M7 environment functions to `revamped/environment.py`; inject a clock only for timestamp consumers. | All M7 environment tests and M8 environment/proxy coexistence tests; deterministic golden argument cases. | Desktop yields `[]`; mobile/custom outputs match exact safe switches; timezone is stored-only; no spoofing flags. | Use legacy environment functions through adapter; leave catalog records unchanged. |
| 4. Proxy normalization | Move M8 proxy helpers to `revamped/proxy.py`. Keep parser credentials transient and redaction/error rules explicit. | All M8 parser, invalid input, IPv6, persistence, off/fallback, isolation, GUI source-boundary, and secret tests. | No network; off yields no switch; enabled output matches exact strings; no credential appears in output/catalog/log. | Disable revamped proxy path and continue using legacy proxy helpers; do not migrate stored data. |
| 5. Models and view records | Introduce typed/internal profile records and pure table-row conversion while translating to legacy dict/tuple shapes at the adapter. | M1–M4 profile tuple/metadata shapes; M6/M7/M8 table/search/sort/selection behavior. | Record conversion is deterministic, non-mutating, stable-ID based, and preserves unknown non-sensitive fields where required. | Keep revamped models test-only; legacy GUI/service continues unchanged. |
| 6. Application metadata storage | Implement a revamped `ProfileCatalogStore` for `config/profiles.json`: version validation, sensitive-key rejection, atomic save, stale-write detection, recovery. | M4 entire metadata suite plus fault-injection cases for parse, duplicate keys, stale bytes, and atomic replace. | Catalog behavior matches legacy for disposable roots; no real `config/profiles.json` read/write; unknown valid fields survive. | Do not publish revamped catalog; legacy remains authoritative at runtime. |
| 7. Legacy compatibility storage | Implement `LegacyStateStore` and mirror/bootstrap adapter for `legacy/data/Local State`; keep old schema and two-file publication/restore semantics. | M1/M2 registry preservation/corruption/lock tests, M3 migration, M4 bootstrap/reconciliation. | Existing legacy catalog can be read and mirrored in fixtures; no Chromium-owned profile internals are rewritten. | Revert to legacy manager for all bootstrap/mirror operations; leave test fixtures disposable. |
| 8. Browser launcher/process boundary | Extract `browser_using_directory`, profile layout validation, deterministic command assembly, and an injected process factory into `revamped/processes.py` and `launcher.py`. | M1 exact command and Popen kwargs; M2 live/restarted/failed/uninspectable process tests; M3 managed root; M7/M8 argument coexistence. | Exact command parity, fail-closed process behavior, no shell, no real process in automated tests. | Do not call revamped launcher from GUI; legacy launcher remains default. |
| 9. Extension management | Extract source validation, per-profile staged deployment, config/extra-file preservation into `revamped/extensions.py`. | M1 extension arguments and account workflow; M5 all source/deployment/restart/missing/invalid/failure/isolation tests. | Source/deployment parity with disposable roots; optional bad deployment never blocks browser; no real extension deployment. | Keep revamped deployer unreferenced; do not clean or rewrite profile deployments. |
| 10. Account management compatibility | Isolate current parser/config/developer-mode workflow behind `revamped/accounts.py`; do not attempt secure credential migration here. | M1/M2 account setup/import/missing-profile; M5 account isolation/restart/log hygiene; M6 account UI paths. | Synthetic account fixtures only; no credentials in new catalog/logs; compatibility behavior is explicit and security limitation documented. | Leave AccountManager entirely legacy; require a human checkpoint before any live-data storage change. |
| 11. Profile lifecycle | Move catalog orchestration, create/rename/delete/migration/last-opened and missing-layout behavior into `revamped/profiles.py`, using the stores and path policy. | M1–M4 lifecycle/migration/failure tests plus new invariant tests for source preservation and no auto-clean. | All lifecycle invariants pass in disposable roots; no real profile path is opened or deleted; lock ordering is documented. | Do not connect lifecycle service to GUI; legacy remains rollback reference. |
| 12. GUI model/controller | Extract cached rows, search/sort, stable selection, status polling, button state, and service error mapping. Keep Tk dialogs thin. | M6 entire suite, M7/M8 GUI tests, plus fake-widget contract tests. | Headless tests pass; no metadata reload during search/status; no proxy probe during status; partial multi-open remains. | Revert to legacy `ProfileManagerApp`; no change to root entrypoint. |
| 13. GUI/dialog composition and revamped main | Add `revamped/gui.py` and `revamped/main.py`; support an explicit development command while stable `main.py` still delegates legacy. | All legacy tests, revamped tests, compatibility tests, verification script, and disposable GUI/manual smoke on a copied project. | Revamped can launch only in an explicitly safe disposable context; legacy command and root command remain unchanged. | Remove/disable revamped command; `main.py` stays legacy. |

The order deliberately keeps account storage after extension and launcher seams are
understood, and keeps destructive lifecycle work after both storage and path safety
contracts are proven. This is safer than extracting the GUI first because the GUI
currently hides several service and filesystem dependencies.

## 10. Proposed Revamped Structure

Do not create these files as part of this inspection. This is a deliberately small
structure: each module should own a meaningful boundary, and tiny one-function
modules should not be added merely for aesthetics.

```text
revamped/
├── __init__.py
├── main.py              # Development-only composition root; runnable with -m
├── core.py              # Errors, ProjectPaths, safe path policy, logging seam
├── processes.py         # Injectable Chromium process inspection and process helpers
├── environment.py       # M7 normalization, effective state, editor state, switches
├── proxy.py             # M8 normalization, parser, effective state, switches
├── models.py            # Profile record/catalog shapes, timestamps, view-row data
├── storage.py           # ProfileCatalogStore, LegacyStateStore, mirror/bootstrap coordinator
├── profiles.py          # Profile lifecycle, discovery, migration, layout validation
├── extensions.py        # Source validation and staged per-profile deployment
├── accounts.py          # Legacy account/extension-config compatibility boundary
├── launcher.py          # Command assembly and injected Chromium launch service
└── gui.py               # Tk application/controller, dialogs, table and selection state
```

Recommended dependency direction:

```text
core / models / environment / proxy / processes
                ↓
             storage
                ↓
             profiles ───────→ extensions
                ↓                    ↓
             launcher ←──────── accounts
                ↓
               gui
                ↓
          revamped.main
```

The arrows are conceptual, not a requirement that every module import every lower
layer. In particular:

- `revamped/__init__.py` must have no filesystem/logging/Tk side effects.
- `core.py` owns injected roots, safe path operations, and error types but does not
  import service modules.
- `environment.py`, `proxy.py`, and most of `models.py` stay deterministic and do
  not import storage or GUI.
- `storage.py` owns file formats and atomic writes; profile services receive stores
  rather than constructing global paths internally.
- `profiles.py` owns lifecycle policy; it should not know Tk widgets or dialogs.
- `launcher.py` receives a profile service, process inspector, executable path, and
  process factory rather than constructing a fresh global manager.
- `accounts.py` is intentionally isolated so later secure credential work can be a
  separate milestone.
- `gui.py` consumes service interfaces and view records; it should not perform raw
  recursive deletion or catalog JSON parsing.
- `revamped.main` performs composition and logging setup explicitly.

## 11. Legacy vs Revamped Parity Strategy

### Test locations and adapters

Keep the existing M1–M8 suite unchanged as the frozen legacy regression suite. Add:

```text
tests/
└── compatibility/
    ├── __init__.py
    ├── fixtures.py
    ├── legacy_adapter.py
    ├── revamped_adapter.py
    ├── test_pure_parity.py
    ├── test_storage_parity.py
    └── test_launch_parity.py
```

The adapters should expose a small common vocabulary, not duplicate the entire
legacy class hierarchy. `legacy_adapter.py` can retain the current dynamic loader
and module-global patching. `revamped_adapter.py` should construct explicit
`ProjectPaths`, stores, fake process factories, and service objects.

### Deterministic comparisons

The best first parity targets are:

- profile ID, managed marker, and path validation;
- relative profile-path serialization and resolution;
- environment preset/config normalization and launch switches;
- proxy scheme/host/port normalization, IPv6 formatting, parser acceptance/rejection,
  and no-credential launch output;
- timestamp conversion with a fixed clock/epoch;
- catalog record creation and legacy-to-application metadata transformations after
  removing nondeterministic timestamp fields;
- Chromium fixed/environment/proxy/extension command argument generation with fixed
  synthetic paths;
- GUI table-row display, filtering, sorting, stable-ID selection, and status
  transitions using fake process/widgets.

### Stateful comparisons

Use disposable fixture roots under `tmp/compatibility-*` with synthetic browser
markers and `example.invalid` test accounts only. Compare invariants after each
operation rather than raw profile contents:

- create → rename → restart → open;
- legacy profile → explicit copy migration → open both source and managed copy;
- catalog missing/empty/malformed/partially malformed;
- delete cancellation, metadata failure, interrupted staging, and cleanup failure;
- extension source update while preserving profile-local config/extra files.

Do not load legacy and revamped into the same process if their module globals can
interact. A proposed `scripts/compare_legacy_revamped.py` should run each backend in
an isolated subprocess or use fully injected settings, emit only normalized
structured results, and never print raw account/config/profile/log data.

### Parity result policy

- Exact equality is required for pure values and launch argument lists.
- For errors, compare error category and safety invariant; exact wording is only
  required where existing user-facing compatibility depends on it.
- For storage, compare catalog/mirror structure after removing permitted formatting
  differences, not raw Chromium profile files.
- A parity failure blocks any `main.py` switch and is investigated before further
  extraction.

## 12. Legacy Freeze Rules

During revamped development, the following are read-only by policy:

1. `legacy/profile_manager.py`: no edits, formatting-only rewrites, import changes,
   bug fixes, renames, or “cleanup” mixed into revamped work. The file is the frozen
   reference implementation and rollback target.
2. `legacy/data/`: no migration, repair, deletion, rewrite, or test fixture creation.
   Existing `Local State` and legacy profile data remain user-owned.
3. `legacy/log/`: no log rotation/cleanup or direct edits. Test loaders may suppress
   setup in disposable executions only.
4. Existing `tests/test_m1_runtime.py` through `tests/test_m8_proxy.py`: treat as
   frozen regression evidence. Add new tests under compatibility/revamped locations
   rather than changing old assertions to fit a new design.
5. The legacy command `python -B .\legacy\profile_manager.py` must remain runnable.
6. No compatibility shim may silently redirect legacy calls to revamped until parity
   and explicit approval are complete.
7. No default entrypoint, packaging, profile path, extension path, or account storage
   change may be smuggled into a “freeze” commit.

Allowed during the freeze: read-only inspection, additive compatibility adapters,
synthetic fixture tests, documentation, and new code under `revamped/` that is not
referenced by the stable entrypoint. If a legacy bug is discovered, record it as a
separate issue and obtain explicit direction before changing the reference file.

## 13. Main Entrypoint Migration Strategy

### Incomplete phase

Keep the current stable behavior exactly:

```text
python -B main.py
    -> legacy.profile_manager.main
```

`main.py` remains the rollback switch and `scripts/verify.py` continues to require
the legacy import text until the migration is explicitly approved.

### Revamped development launch

Provide a separate module command:

```powershell
python -B -m revamped.main
```

For unattended or automated development, the revamped composition must use a
disposable root, for example a command-line `--workspace-root`/`--data-root` fixture
under `tmp/`. The development entrypoint should refuse or clearly require an
explicit opt-in before using the real project `profiles/`, `legacy/data/`,
`config/profiles.json`, or extension deployments. This prevents a parallel build
from mutating live data merely because the module was launched.

The exact safe CLI flag is a design detail to settle in R1, but the safety invariant
is not optional: no revamped development run should silently share real profile data.

### Switch conditions

Do not change `main.py` until all of the following are true:

- legacy full suite and revamped suite pass;
- legacy-vs-revamped deterministic and stateful compatibility tests pass;
- `scripts/verify.py` is updated only through a separately reviewed change and
  passes;
- no real profile/config/browser data was touched by automated verification;
- manual GUI acceptance has been performed by the user using disposable profiles;
- rollback has been rehearsed by returning `main.py` to the legacy target;
- packaging remains locked; and
- the user explicitly approves switching the stable entrypoint.

Until then, the two implementations are parallel, with legacy authoritative and
revamped development-only.

## 14. Refactor Completion Gates

Revamped is not ready to become the default implementation until every gate below
is objectively satisfied:

1. Existing full unit suite: `170/170` tests pass with no weakening or deletion of
   legacy assertions.
2. Revamped unit tests pass, including pure helpers, stores, process/launcher
   fakes, extension staging, lifecycle failure paths, and headless GUI model tests.
3. Legacy-vs-revamped compatibility tests pass for deterministic values and the
   agreed stateful fixture scenarios.
4. `python -B scripts/verify.py` passes, including syntax, unit tests, stable
   entrypoint, and runtime structure checks.
5. A no-real-data audit confirms automated tests use disposable roots and did not
   write `profiles/`, `legacy/data/`, the real `config/profiles.json`, extension
   deployments, logs, or the browser runtime. The audit must not print their raw
   contents.
6. Manual GUI acceptance is completed by the user from `docs/MANUAL_ACCEPTANCE.md`:
   startup, restart, create/open, isolation, rename, multi-open/running state,
   synthetic import, extension loading, environment, proxy, deletion, alternate
   working directory, and safe missing-runtime behavior.
7. Real Discord behavior remains a separately recorded optional result and is never
   inferred from unit tests or the local smoke fixture.
8. A human-approved rollback path remains available: `main.py` can point to legacy,
   and legacy remains runnable without data migration.
9. Packaging is still locked. No `.exe`, installer, updater, runtime replacement,
   or release artifact is part of refactor completion.
10. The user explicitly approves default-entrypoint migration after reviewing the
    evidence.

The manual GUI gate is intentionally still pending in this inspection. Automated
success is not manual acceptance.

## 15. Overnight Automation Risks

### Safe autonomous work

Codex can safely perform the following in a disposable/test-only or source-only
context:

- add the `revamped/` scaffolding without wiring it into `main.py`;
- add pure normalization, model, and deterministic compatibility tests;
- build fault-injection tests using temporary roots and synthetic accounts;
- add the legacy/revamped adapters and a compare script that emits normalized,
  secret-free results;
- inspect source, Git history, static structure, and test failures;
- update refactor documentation and milestone status;
- run syntax checks and the existing unit suite;
- improve test doubles and test-only process/filesystem fakes;
- add static assertions that the legacy file and stable entrypoint remain unchanged.

### Human checkpoint required

Stop and obtain explicit direction before:

- editing `legacy/profile_manager.py`, existing tests, or the stable `main.py`;
- connecting revamped to real `profiles/`, `legacy/data/`, `config/`,
  `extensions/`, `logs/`, or `browser/` paths;
- launching Chromium outside a disposable fixture;
- any migration, deletion, repair, cleanup, or rewrite of real profile data;
- changing account credential storage, reading live credentials, secure-storage
  migration, or credential-bearing proxy behavior;
- changing extension deployments or Chromium runtime files;
- running manual GUI/Discord acceptance on behalf of the user;
- enabling packaging, installer, release, browser updater, or rollback work;
- adding anti-detection/fingerprint spoofing, token extraction, proxy rotation, or
  network provider integration.

Do not recommend overnight automation that depends on “cleaning up” failed staged
directories broadly. Interrupted deletion and migration paths are deliberately
fail-closed and must be inspected by a human before any cleanup.

## 16. Proposed Refactor Milestones

Packaging is intentionally absent from this milestone sequence and remains LOCKED.

| Milestone | Scope | Exit evidence |
| --- | --- | --- |
| **R0 — Baseline/freeze** | Capture the post-M11 Git/test baseline; declare legacy/profile/runtime/config freeze rules; confirm no `revamped/` exists yet. | `verify.py` PASS, full suite `170/170`, no tracked diff, no real-data writes, freeze checklist accepted. |
| **R1 — Architecture + contract tests** | Add the proposed dependency contracts, disposable fixture factory, legacy/revamped adapters, and first deterministic parity harness. | Pure contract harness runs against legacy only first; no stable-entrypoint change; no profile data touched. |
| **R2 — Pure helpers** | Extract path/ID/link policy, serialized path conversion, timestamp/model primitives, and safe error categories. | M2–M4 safety and metadata contract cases pass; path failures are fail-closed. |
| **R3 — Environment + proxy** | Add revamped M7/M8 normalization and argument modules with transient proxy parse boundary. | M7/M8 deterministic parity passes; no network, credentials, rotation, or spoofing. |
| **R4 — Storage** | Implement application catalog storage, legacy state adapter, bootstrap/reconciliation, mirror publication, and atomic/stale-write behavior. | M1–M4 storage parity and fault cases pass in disposable roots; real catalog untouched. |
| **R5 — Launcher + processes** | Implement injected process detection, browser layout validation, and exact command assembly. | M1–M3/M7/M8 launcher parity passes with no real process start in automated tests. |
| **R6 — Extensions + accounts** | Implement staged extension deployment and isolate the legacy account workflow behind a compatibility service. | M1/M5 account/extension tests and secret-hygiene contracts pass with synthetic data only. Secure credential migration remains out of scope. |
| **R7 — Profile lifecycle** | Implement create/rename/delete/migration/last-opened and recovery semantics over revamped stores. | M1–M4 lifecycle/migration invariants pass; failure paths preserve source and staging correctly. |
| **R8 — GUI model + application UI** | Implement cached rows, selection/search/sort/status model, then thin Tk dialogs/actions. | M6–M8 headless GUI behavior passes; manual GUI checklist prepared but not claimed complete. |
| **R9 — Revamped integration** | Compose `revamped.main`, safe disposable development launch, and service wiring. Keep `main.py` on legacy. | `python -B -m revamped.main` works only in the approved disposable/dev context; legacy command and verification remain unchanged. |
| **R10 — Parity verification + migration decision** | Run complete legacy/revamped compatibility matrix, verify no real-data writes, perform manual acceptance with the user, and document rollback. | All completion gates in section 14 pass; only then may the user decide whether to switch `main.py`. |

There is no R11 packaging milestone in this proposal. Packaging requires a separate
explicit user instruction after source-app approval.

## 17. Final Recommendation

### Recommendation

The repository is currently safe to begin an **additive, parallel, development-only
revamped refactor**. The baseline is strong enough to start: the tracked source
tree is clean, M8–M11 are committed, the verification script passes, and all 170
unit tests pass.

It is **not** safe to declare revamped production-ready, connect it to real profile
data, or switch `main.py` yet. The first required work is R0/R1: freeze legacy,
preserve the current test seams, create disposable compatibility fixtures, and add
deterministic parity tests before moving stateful behavior. The user must still
perform the manual GUI acceptance described in `docs/MANUAL_ACCEPTANCE.md`; no GUI,
real-Chromium, or real-Discord result is claimed here.

The main risks to resolve before any default switch are:

- the current suite tests legacy by dynamic source execution and module-global
  patching, so a normal import-based refactor will not automatically be covered;
- `ProfileManager` couples application catalog, legacy mirror, filesystem lifecycle,
  and migration rollback;
- `ChromiumLauncher` constructs a second manager implicitly and combines process,
  path, metadata, environment, proxy, and extension concerns;
- `AccountManager` still uses legacy plaintext profile-local configuration and must
  remain an isolated compatibility boundary;
- GUI behavior is partly tested by source inspection and hand-built Tk doubles;
- the existing untracked handoff/status notes contain historical pre-M8 wording and
  should not replace the current Git/test evidence; and
- packaging remains LOCKED.

The safe decision is therefore: begin R0/R1 and additive pure-helper work if desired;
keep `legacy/profile_manager.py` and `main.py` authoritative; do not touch real
profiles, credentials, browser runtime, or packaging; and require explicit user
approval after all parity and manual gates before any entrypoint migration.

