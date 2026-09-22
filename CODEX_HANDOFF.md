# Discord Profile Manager — Codex Handoff

Inspection snapshot: 2026-09-15, Windows, repository `I:\Discord_Profile_Manager`.

This document is based on the current working tree, the tracked Git history, the
source/tests/documentation, and a read-only inventory of the local runtime/profile
directories. Local browser/profile/account data was not copied into this document;
no credential values, tokens, TOTP secrets, or account contents are intentionally
included.

The working tree is not clean. In particular, the current source contains an
uncommitted M8 proxy implementation and an untracked M8 test file. This handoff
describes the current working tree where relevant, while distinguishing it from
the latest committed M7 baseline.

## 1. Project Overview

Discord Profile Manager is a Windows desktop application for operating multiple
isolated Discord browser sessions through a bundled Ungoogled Chromium runtime.
The application is a Python/Tkinter GUI launched from
`legacy/profile_manager.py`. It is a browser profile manager, not a Chromium fork.

Its intended behavior is:

- keep `browser/chrome.exe` and the rest of the Chromium runtime separate from
  application configuration and user profile data;
- create, rename, delete, search, sort, and launch independent Chromium user-data
  roots;
- support opening multiple profiles at once and report live browser state;
- preserve older profiles stored below `legacy/data/` and offer an explicit,
  copy-only migration into `profiles/`;
- maintain application-owned profile metadata in `config/profiles.json` while
  retaining the older Chromium-style `legacy/data/Local State` file as a
  compatibility mirror when present;
- optionally deploy the supported Discord autofill extension separately into each
  profile, with profile-specific account configuration;
- provide per-profile browser environment presets (M7) and, in the current
  uncommitted working tree, unauthenticated per-profile proxy configuration (M8
  work in progress).

The long-term requirements also call for secure credential storage, a browser
runtime manager/updater, Windows packaging, and eventual modularization. Those
items are not complete.

## 2. Current Architecture

### Entry point and path model

There is one application module and one executable entry path:

```text
python -B legacy/profile_manager.py
```

At import time, the module resolves paths from the script location rather than the
current working directory (`legacy/profile_manager.py:34-48`). The important paths
are:

| Path | Role |
| --- | --- |
| `browser/chrome.exe` | Bundled Chromium executable required for startup/launch. |
| `config/profiles.json` | Application-owned profile catalog, version 1. |
| `legacy/data/Local State` | Pre-M4 legacy registry and optional compatibility mirror. |
| `profiles/profile_####/` | Managed independent Chromium user-data roots for new/migrated profiles. |
| `legacy/data/<profile id>/` | Unmarked legacy profile roots that have not been explicitly migrated. |
| `extensions/discord-autofill-extension/` | Supported reusable unpacked extension source. |
| `<profile root>/Unpacked Extensions/discord-autofill-extension/` | Profile-local extension deployment. |
| `legacy/log/` | Actual application log directory. The top-level `logs/` directory is currently empty. |

The module has import-time logging setup and creates the legacy log directory. The
test harness patches these side effects while loading the module.

### Main components in `legacy/profile_manager.py`

The file is over 4,100 lines and contains all of the following:

1. Validation/path helpers: profile ID validation, Windows reserved-name checks,
   containment checks, reparse-point/link rejection, and running-process detection.
2. `LocalStateManager` (`:239-378`): reads/writes the legacy Chromium-shaped
   `Local State`, uses `.manager.lock` to serialize operations, validates the old
   registry, and performs guarded atomic replacement.
3. Environment/proxy normalization helpers (`:399-852` in the current tree):
   normalize M7 desktop/mobile/custom settings and the uncommitted M8 proxy
   settings before launch.
4. `ProfileMetadataManager` (`:887-1029`): validates and atomically replaces
   `config/profiles.json`; rejects sensitive field names such as password/token/
   TOTP/session-like fields.

The application catalog has the shape `{version: 1, profiles: [...]}`. Each
record requires `profile_id`, `display_name`, `profile_directory`, `created_at`,
`last_opened_at`, and `proxy_enabled`; environment settings and valid proxy
endpoint fields are optional launch metadata. The legacy registry keeps entries
under `profile.info_cache[profile_id]`, with the display name, creation time, and
an optional `manager_path` marker for managed roots.
5. `ProfileManager` (`:1034-1771`): bootstraps/reconciles the catalog, creates
   profile roots, resolves legacy vs managed paths, renames, deletes, migrates,
   records last-opened timestamps, and validates independent Chromium layouts.
6. `ExtensionManager` (`:1776-1990`): validates the root extension source and
   staged profile deployments; preserves profile-local `config.js` and extra files
   while refreshing reusable source files.
7. `AccountManager` (`:1991-2211`): parses `email:password[:totp]`, writes the
   profile-local extension configuration, enables Chromium developer mode, reads
   existing account config, masks values for display, and removes/reset accounts.
8. `ChromiumLauncher` (`:2216-2287`): builds per-profile command lines, checks
   runtime/profile/process state, passes environment/proxy/extension switches, and
   launches Chromium directly with `subprocess.Popen`.
9. `ProfileManagerApp` (`:2292-4090`): the Tkinter GUI, cached table model, search,
   sorting, multi-selection, status polling, dialogs, profile actions, account
   workflows, environment editor, and current proxy editor.
10. `main()` (`:4095-4163`): checks the runtime, initializes compatibility and
    application metadata, creates the GUI, and handles shutdown/fatal errors.

### Data flow

1. `main()` verifies that `browser/chrome.exe` is a file. A missing runtime is
   reported in a dialog and returns without opening the main window.
2. `ProfileManager.initialize_metadata()` acquires the manager lock and loads
   `profiles.json`. If it is absent/empty, it bootstraps from the legacy registry
   and physically recognizable managed/legacy roots without deleting or moving
   them.
3. `ProfileManager` treats `profiles.json` as authoritative after bootstrap. It
   may reconcile newly discovered managed roots and legacy registry entries. The
   legacy registry is kept as a mirror only when it was active/present.
4. The GUI calls `get_profile_metadata()`, builds cached rows, and polls only live
   browser status every 1.5 seconds. Search/sort operate on cached rows.
5. Opening a profile resolves and validates its registered directory, rejects
   shared-root/ambiguous layouts, gathers any valid optional profile-local
   extension deployment, builds Chromium arguments, and launches the isolated root.
6. A successful launch updates `last_opened_at`. Multiple selected profiles are
   requested independently; one failure does not stop the remaining requests.
7. Account setup validates the input, stages the extension source, preserves or
   creates profile-local files, and writes the selected profile's `config.js` only.
8. Delete first stages the active directory as `.deleting-<id>-<unique suffix>`,
   publishes catalog changes, then removes the staged directory. Failed metadata
   publication attempts to restore the original directory; failed cleanup is
   reported and is not automatically retried on restart.

### Environment and proxy behavior

M7 environment support is present in the committed M7 baseline and current tree:

- `desktop`/legacy `default`: no environment switches;
- `mobile`: generic Chromium mobile user agent, touch events, 390x844 window,
  `en-US`, and the current working-tree device scale factor of `1.0`;
- `custom`: safe viewport, scale, locale, mobile/touch fields;
- timezone values are validated/persisted but are explicitly not applied by the
  launcher because there is no CDP/session layer;
- this is not deep fingerprint spoofing and does not emulate a branded device.

The current uncommitted M8 work adds:

- `http`, `https`, `socks4`, and `socks5` endpoint validation;
- per-profile `proxy_enabled`, scheme, host, and port metadata;
- a Chromium `--proxy-server=...` switch only for a valid enabled profile;
- proxy-off default/fallback behavior for missing or malformed optional metadata;
- a GUI paste parser for common endpoint formats.

Proxy authentication is intentionally not supported in M8. Credential-bearing
input can be parsed so the UI can explain the limitation, but username/password
values are not accepted by `set_proxy()`, not persisted in the catalog, and not
put in the proxy launch switch.

## 3. Repository Map

### Important tracked files/directories

- `AGENTS.md` — repository-specific development/safety rules supplied to Codex.
- `REQUIREMENTS.md` — product requirements and future priority order.
- `README.md` — run instructions, M1-M5 compatibility behavior, test commands, and
  manual acceptance checklists. It does not yet provide a clean current M6-M8
  status summary.
- `legacy/profile_manager.py` — the complete application implementation; despite
  the directory name, it is the current entry point.
- `extensions/discord-autofill-extension/manifest.json` — MV3 manifest for the
  only supported extension.
- `extensions/discord-autofill-extension/config.js` — empty account template.
- `extensions/discord-autofill-extension/content.js` — Discord login/2FA DOM
  autofill watcher.
- `extensions/discord-autofill-extension/totp.js` — client-side Base32/HMAC-SHA1
  TOTP generation.
- `extensions/discord-autofill-extension/icons/` — extension icons.
- `tests/test_m1_runtime.py` — path/runtime/launch/profile/account regressions;
  disposable data and mocked processes.
- `tests/test_m2_lifecycle.py` — metadata safety, process checks, deletion,
  multi-open, links, layout compatibility, and lifecycle failure handling.
- `tests/test_m3_migration.py` — copy-only legacy-to-managed migration behavior.
- `tests/test_m4_metadata.py` — application catalog bootstrap, recovery,
  validation, persistence, and atomic-write behavior.
- `tests/test_m5_extensions.py` — extension discovery, staging, isolation,
  restart compatibility, and source/deployment failures.
- `tests/test_m6_gui.py` — GUI model/display behavior with fake Treeview/Tk values;
  it does not require a visible desktop.
- `tests/test_m7_environment.py` — environment presets, normalization, launch
  flags, GUI editor state, and no-fingerprint-spoofing regressions.
- `tests/test_m8_proxy.py` — currently untracked tests for the working-tree M8
  proxy implementation; `unittest discover` includes them locally.
- `tests/browser_smoke_m2.py` — opt-in real Chromium, headless, loopback storage
  isolation smoke test.
- `.gitignore` — excludes the browser runtime, profiles, local data, logs,
  `profiles.json`, temporary data, virtual environments, and generated binaries.
- `LICENSE` — GNU General Public License v3 text.

### Local/runtime directories

These are significant to the application but are not reproducible from Git in the
current repository because they are ignored or local-only:

- `browser/` — a complete local Chromium runtime. The current manifest identifies
  version `152.0.7977.82`; the directory is about 436 MB and is ignored.
- `profiles/` — current managed Chromium data. At inspection time it contained 10
  managed roots (`profile_0001` through `profile_0010`), all with `Default/Preferences`
  and profile-local autofill deployments. This is live user data and must not be
  deleted or rewritten casually.
- `config/profiles.json` — currently present, version 1, with 10 records at
  inspection time (8 `default`, 1 `custom`, 1 `mobile`) and no enabled proxies.
  It is ignored by Git.
- `legacy/data/` — currently contains the manager lock and legacy `Local State`,
  but no legacy profile directory was observed at the top level.
- `legacy/log/` — current application logs. Do not assume logs are safe to print;
  inspect them only with secret redaction.
- `logs/` — currently empty and not the path used by the legacy module.
- `tmp/` — disposable test/smoke data and retained failed smoke-test directories;
  ignored and not part of the product state.

There are no tracked `pyproject.toml`, `setup.py`, `requirements.txt`, `Pipfile`,
Makefile, installer specification, linter configuration, type-checker
configuration, CI workflow, or separate package/module tree.

## 4. Current Development Status

No dedicated milestone/status file exists. The milestone reconstruction below is
inferred from commit messages, tests, source comments, and README behavior.

| Milestone | Status | Evidence and limits |
| --- | --- | --- |
| M1 | Completed/inferred | Baseline direct-runtime/profile/account/extension behavior is covered by `test_m1_runtime.py`; there is no dedicated M1 commit or status file. |
| M2 | Completed in Git baseline | Commit `287464e` (“Stabilize direct Chromium profile lifecycle (M2)”), lifecycle tests, path safety, process detection, multi-open, guarded delete, and compatibility checks. Real-browser smoke is environment-sensitive and currently fails on this machine. |
| M3 | Completed in Git baseline | Commit `ce83066`; explicit copy-only migration to `profiles/`, collision avoidance, link rejection, source preservation, and migration tests. |
| M4 | Completed in Git baseline | Commit `a7a1c28`; application-owned `config/profiles.json`, bootstrap/reconciliation, atomic writes, validation, and legacy mirror behavior. |
| M5 | Completed in Git baseline | Commit `689fab4`; safe single-extension discovery/deployment, profile-local configuration isolation, staged updates, optional launch behavior, and tests. |
| M6 | Completed in Git baseline | Commit `ea05448`; responsive scrollable GUI sidebar, cached table/search/sort, multi-selection, status polling, and GUI model tests. |
| M7 | Committed but locally adjusted | Commit `24f7716`; desktop/mobile/custom environment presets and tests. The current working tree changes the mobile default device scale factor from `2.0` to `1.0` and changes the M7 test expectation accordingly. |
| M8 | Implemented in current working tree, not committed | Adds optional unauthenticated proxy configuration, safe parsing/validation, launch flags, GUI, and 33 tests. It is represented by modified `legacy/profile_manager.py`, modified `tests/test_m7_environment.py`, and untracked `tests/test_m8_proxy.py`. Authentication and connectivity validation are not implemented. |
| M9+ | Not started/UNKNOWN | Secure credential migration, runtime updater/rollback, packaging, and modularization are requirements/future work only. |

### Functionality that is currently present

- direct launch through `browser/chrome.exe`, without Portapps or
  `ungoogled-chromium-portable.exe`;
- isolated managed profile roots with minimal Chromium `Default/Preferences`;
- legacy profile compatibility and explicit copy-only migration;
- application-owned metadata with guarded recovery and atomic replacement;
- create, rename, delete, search, sort, multi-select, live status, and multi-open;
- profile-local unpacked Discord autofill extension deployment;
- account import from TXT and per-profile account configuration;
- M7 environment presets and safe launch arguments;
- current uncommitted M8 unauthenticated proxy configuration.

### Functionality that is partial or unfinished

- account credentials/TOTP are still stored as plaintext in profile-local
  extension `config.js`; secure Windows credential storage is not implemented;
- timezone is stored but not applied at launch;
- proxy authentication, proxy connectivity testing, rotation, and provider
  integration are not implemented;
- browser runtime detection/update/recovery/rollback is not implemented;
- Windows executable packaging is not implemented;
- the code is still a single monolithic legacy module;
- visible GUI/manual acceptance has not been performed in this inspection;
- README documentation has not been updated into a unified M6-M8 status document.

## 5. Existing Invariants / Behaviors That Must Not Break

These are safety and compatibility contracts for future changes:

1. Launch the bundled runtime at `browser/chrome.exe`. Do not reintroduce
   Portapps or `ungoogled-chromium-portable.exe` assumptions.
2. Keep browser runtime, application metadata, Chromium profile data, extension
   source, and logs in separate areas. Browser updates must never delete
   `profiles/`, `config/`, `extensions/`, or logs.
3. Resolve project paths from the script/project root, not the process current
   directory. Paths containing spaces and Unicode must remain supported.
4. Never automatically reset, overwrite, replace, or recreate malformed/missing
   profile metadata or profile directories. Report the problem and preserve the
   user’s files.
5. Profile IDs and stored paths must remain Windows-safe, contained under the
   approved root, and free of symlinks/junctions/reparse points. Do not relax the
   link/path checks for convenience.
6. Every opened profile must use an independent Chromium user-data directory.
   Do not silently open a shared-root subprofile as a new empty profile.
7. Existing legacy profiles remain at `legacy/data/<id>` until the user explicitly
   calls migration. `migrate_profile()` is copy-only and must leave the source
   untouched on success or failure.
8. Deletion must require deliberate user confirmation, must not delete a running
   profile, and must preserve/report staged data on metadata or cleanup failure.
9. Running-state detection must work across manager restarts and must fail closed
   when Chromium process identity cannot be inspected.
10. `profiles.json` must remain application-owned and must not contain passwords,
    tokens, TOTP secrets, cookies, session values, or proxy credentials. Unknown
    non-sensitive valid application fields should remain preservable.
11. Logs and error messages must not include passwords, authentication tokens, TOTP
    secrets, or proxy credentials. Do not print current local profile/config files
    during diagnostics.
12. Extension configuration must remain isolated per profile. Refreshing reusable
    extension files must preserve that profile’s `config.js` and extra local files.
13. Invalid optional environment/proxy configuration must not make a profile
    unlaunchable; safe fallback is desktop/proxy-off behavior.
14. Proxy-off profiles must receive no `--proxy-server` switch. Current M8 proxy
    work must not begin storing or launching authentication credentials.
15. GUI selection must be resolved by stable profile ID, not display name, icon,
    or row position. Search/sort should not mutate profile metadata.
16. Unit tests use disposable directories and monkeypatch the module’s global
    paths/processes. Preserve the public names and test seams unless a migration
    is deliberate and the whole suite is updated.

## 6. Build and Verification

### Prerequisites/install

The repository has no dependency manifest. The README identifies Python with
Tkinter and `psutil` as the runtime requirements. The inspected environment was:

- Python 3.11.8
- `psutil` 7.2.2
- Tkinter 8.6
- `sys.platform == win32`

Install the only non-standard Python dependency with:

```powershell
python -m pip install psutil
```

Tkinter must be available in the selected Python installation. The complete
Chromium runtime must be supplied separately under `browser/`; there is no runtime
download/install script.

### Development/run command

From the project root:

```powershell
Set-Location -LiteralPath 'I:\Discord_Profile_Manager'
python -B .\legacy\profile_manager.py
```

The path resolver is intended to allow a different working directory too:

```powershell
Set-Location -LiteralPath 'I:\Discord_Profile_Manager\config'
python -B '..\legacy\profile_manager.py'
```

### Automated unit tests

Exact documented command:

```powershell
python -B -m unittest discover -s tests -v
```

Observed result on 2026-09-15: **PASS — 170 tests, OK, about 8 seconds**.
This count includes the untracked `tests/test_m8_proxy.py` because unittest
discovery sees it in the working tree. The tests use synthetic data and mocked
processes/dialogs; they do not log into Discord or use production account data.

### Real Chromium smoke test

Exact command:

```powershell
python -B tests/browser_smoke_m2.py
```

Observed result on 2026-09-15: **FAIL before fixture completion**. Chromium exited
with code `2147483651`; diagnostics reported GPU process failure, a persistent GPU
cache sharing violation (`0x20`), and “GPU process isn't usable”. The script then
hit a second failure while printing the retained disposable path because the
default Windows cp1252 stdout could not encode the Unicode character in its
`m2 smoke Thử` temporary directory name. The failed disposable directory was
retained under `tmp/` as designed. This does not prove normal visible GUI launches
fail; those remain manually unverified.

The smoke test is intended to verify concurrent isolated storage, cookies,
Local Storage, IndexedDB, manager/browser restart persistence, rename persistence,
safe deletion, and runtime/legacy-state non-modification. It uses a loopback HTTP
fixture and disposable paths only.

### Build/packaging

No build or packaging command exists. There is no PyInstaller spec, installer
script, executable output, or dependency-bundling workflow. The requested final
Windows distribution is therefore **NOT IMPLEMENTED**.

### Linting/type checking

No Ruff/Flake8/Pylint configuration, mypy/pyright configuration, or project lint/type
command exists. No dedicated lint or type check was run. The passing unittest
suite necessarily imports/compiles the Python module and exercises the implemented
behavior, but it is not a substitute for static analysis.

### Other verification performed

The following environment check passed:

```powershell
python --version
python -c "import psutil, tkinter, sys; print('psutil', psutil.__version__); print('tkinter', tkinter.TkVersion); print('platform', sys.platform)"
```

An in-memory syntax compilation check also passed for the application module and
all nine Python test/smoke files:

```powershell
python -B -c "from pathlib import Path; paths=[Path('legacy/profile_manager.py'), *Path('tests').glob('*.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in paths]; print('syntax: OK', len(paths), 'files')"
```

The local runtime manifest was inspected and reports Chromium version
`152.0.7977.82`. No source/build files were found for a separate compile/build
step.

Manual acceptance checks are documented in `README.md` (startup, creation,
isolation, rename/restart, synthetic account import, extension loading, deletion,
different working directory, missing runtime, additional M2 checks, and M3
migration checks). They were not performed during this handoff inspection.

## 7. Known Problems

1. **Real-browser smoke failure in the inspected environment.** The local Chromium
   build/graphics environment crashes in the GPU process during the headless smoke
   test. The README already warns about this class of failure. A normal GUI launch
   still requires manual validation.
2. **Smoke failure reporting is not Unicode-safe.** The smoke test deliberately
   creates a Unicode temporary path, but its failure `print()` can raise
   `UnicodeEncodeError` under cp1252. This can hide the retained path and should be
   fixed in a future test-only change, for example by using UTF-8 output or an
   ASCII-safe path in the diagnostic.
3. **Credentials remain plaintext.** Account email/password/TOTP are written into
   profile-local unpacked extension `config.js` so the current content script can
   read them. `profiles.json` and logs are protected from those values, but this is
   not secure storage. A secure migration must preserve compatibility first and
   must not print existing values.
4. **M8 is not a committed milestone.** The current proxy implementation and its
   test file are local working-tree changes. They have passing unit coverage but
   have not been reviewed/committed as a milestone and have no real proxy
   connectivity coverage.
5. **M7 documentation/version drift.** README sections are primarily M1-M5 and
   still contain the historical statement that M5 does not implement environment
   or proxy behavior. The M7 environment implementation is committed; current M8
   proxy behavior is uncommitted. The README should be updated after the milestone
   decisions are settled.
6. **No reproducible runtime/data checkout.** Chromium, profiles, local metadata,
   logs, and temporary fixtures are ignored. A clean clone cannot run the GUI until
   a compatible runtime is placed under `browser/` and local data roots are created.
7. **No package/build/update workflow.** The app remains a source-run Python script;
   there is no portable Manager executable, dependency lock, runtime version
   manager, update rollback, or CI job.
8. **Monolithic implementation.** Storage, migration, process inspection, account
   handling, extension deployment, launcher, and GUI are tightly coupled in one
   module. Small changes can affect unrelated behavior and tests rely on global
   constants/monkeypatching.
9. **Import is not transactional across all accounts.** TXT import creates each
   profile and configures its account in a loop. If a later line fails, earlier
   profiles remain; there is no batch rollback or recovery UI.
10. **Timezone is only metadata.** The UI labels it “stored only” and the launcher
    does not apply it. This is intentional current behavior, but it can surprise a
    caller who expects environment settings to be fully effective.
11. **Proxy support is intentionally narrow.** Authentication, rotation, proxy
    health checks, and network error handling are absent. An accepted endpoint
    means only that it passed local syntax validation; it does not mean the proxy
    is reachable or valid.
12. **Unexpected fatal GUI errors can request console input.** `main()` logs the
    fatal exception, prints it, and calls `input()` before exit. In a windowed or
    future packaged context without a usable console, that fallback can hang.
13. **Visible GUI and real Discord behavior remain unverified here.** GUI tests use
    fakes, and the browser smoke test uses a local fixture. Account autofill and
    TOTP behavior against Discord should only be checked manually with synthetic or
    explicitly approved test accounts, never production credentials in development.

## 8. External Dependencies

- **Operating system:** Windows is the primary/required target. Windows process
  names, command-line parsing, file locks, reserved names, reparse points, and
  `subprocess.CREATE_NO_WINDOW` are part of the implementation. Non-Windows code
  paths exist mainly for unit-test portability.
- **Python:** Python 3.11.8 was used for the inspected run. The code uses standard
  library modules including Tkinter, `zoneinfo`, `psutil` (third party), JSON,
  `subprocess`, `pathlib`, `tempfile`, and `uuid`.
- **psutil:** Required for live Chromium process detection, parent/child process
  handling, and safe rename/delete/account mutation checks.
- **Tkinter:** Required for the desktop GUI; it must be present in the Python
  distribution.
- **Chromium:** A complete Ungoogled Chromium runtime is expected in
  `browser/`, currently version `152.0.7977.82` by its local manifest. The app does
  not download, install, validate, or update it beyond checking that
  `chrome.exe` is a file.
- **Discord:** Normal launches navigate to `https://discord.com/app`. The app’s
  extension matches `https://discord.com/*`. No Discord API integration is used.
- **Loopback test server:** `browser_smoke_m2.py` starts a local HTTP server and
  does not require external network access. The real browser can nevertheless
  depend on local graphics/Windows environment behavior.
- **Proxy:** Current M8 work passes unauthenticated HTTP/HTTPS/SOCKS4/SOCKS5
  endpoint switches to Chromium. There is no provider service, rotation service,
  or proxy credential store.
- **Timezone data:** `zoneinfo` validation requires a usable IANA timezone data
  source on the host. No separate `tzdata` dependency is declared.
- **Credentials:** No credentials or environment variable values are required to
  run tests. Existing account data may exist in ignored profile-local extension
  files. Never expose it in logs, diagnostics, commits, or handoff documents.
- **Environment variables:** None are documented or required by the application.
  Python must be discoverable as `python`; the browser path is project-relative.

## 9. Risk Areas

1. **Profile filesystem operations:** create, copy, rename, staged delete, atomic
   restore, and recursive cleanup can cause irreversible data loss if containment,
   link detection, running-process checks, or error rollback are weakened.
2. **Two metadata stores:** `profiles.json` is authoritative after bootstrap, but
   `Local State` may be mirrored for compatibility. Ordering and rollback between
   the two files must remain safe under interruption or concurrent edits.
3. **Chromium process detection:** process command lines can be inaccessible for
   sandboxed children; parent traversal and Windows path alias/case behavior are
   deliberately defensive and easy to regress.
4. **Credentials and extension deployment:** extension copies contain per-profile
   sensitive data; staging must preserve each profile’s config and must never
   cross-contaminate accounts.
5. **Launcher arguments:** profile roots, extension lists, environment flags,
   proxy flags, commas, spaces, Unicode, and shell-free Windows process creation
   all need to remain correct together.
6. **GUI cached state:** selection must survive refresh/search/sort by stable ID;
   status polling must not reload or mutate metadata unexpectedly.
7. **Working-tree M8 changes:** any future agent that assumes `HEAD` is the whole
   implementation will miss the current proxy code/test changes. Do not reset or
   discard them without explicit user instruction.
8. **Ignored live data:** the current workspace contains real-looking Chromium
   profile trees and account-capable extension deployments. Tests must use isolated
   temporary roots, and diagnostic commands must avoid dumping contents.
9. **Runtime compatibility:** this project relies on a specific local Chromium
   build and has no automated update/rollback or version compatibility matrix.

## 10. Recommended Next Work

### 1. Review and close out M8 proxy support

- **Objective:** Decide whether the current uncommitted proxy feature is the
  intended M8 scope; review it, document it, and commit it only after approval.
- **Affected components:** current proxy helpers and metadata methods in
  `legacy/profile_manager.py`, GUI proxy dialog, `tests/test_m8_proxy.py`,
  `README.md`, and possibly `config/profiles.json` compatibility behavior.
- **Dependencies:** Windows Chromium argument behavior; no external proxy service
  is required for unit tests.
- **Risks:** leaking credentials, activating malformed/stale proxy fields,
  breaking desktop/mobile flags, or changing the user’s current working tree.
- **Suggested verification:** rerun the full unittest suite; test proxy-off and
  endpoint-specific command lines; manually launch disposable profiles with a
  controlled unauthenticated local proxy if actual network behavior is required.

### 2. Fix/document the real Chromium smoke path

- **Objective:** Make the opt-in smoke test produce a reliable diagnostic under
  Windows Unicode output and determine whether the local GPU failure is a runtime
  configuration issue, sandbox limitation, or Chromium-build incompatibility.
- **Affected components:** `tests/browser_smoke_m2.py`, local Chromium launch flags,
  and README test notes.
- **Dependencies:** a normal Windows terminal and a disposable runtime/profile
  area; do not use existing account profiles.
- **Risks:** changing smoke flags could make the test less representative of normal
  launches; killing the wrong Chromium process could affect user sessions.
- **Suggested verification:** use UTF-8-safe diagnostics, run from a normal
  terminal, confirm all disposable processes are terminated, and compare runtime
  inventory plus legacy metadata before/after. Separately perform the visible GUI
  manual checklist.

### 3. Perform the documented manual acceptance pass

- **Objective:** Verify actual startup, create/open/isolation, rename/restart,
  synthetic account import, extension loading, deletion, alternate working
  directory, missing-runtime behavior, M2 safety cases, and M3 copy-only migration.
- **Affected components:** the entire GUI/launcher/storage path and README
  acceptance checklist.
- **Dependencies:** disposable profiles, a safe test copy for intentional metadata
  damage, and no production credentials.
- **Risks:** accidental deletion or launch of current local profiles; test copies
  must be clearly isolated before modifying metadata/directories.
- **Suggested verification:** follow `README.md` steps exactly, record executable
  and user-data paths from `chrome://version`, confirm data isolation, then report
  each manual result separately from mocked unit-test results.

### 4. Design a secure credential migration

- **Objective:** Replace plaintext account/TOTP storage with an appropriate Windows
  protected storage design while preserving existing profiles during migration.
- **Affected components:** `AccountManager`, extension configuration contract,
  account dialogs/import, profile-local deployments, logs, and documentation.
- **Dependencies:** a deliberate compatibility/migration design; likely Windows
  DPAPI/Credential Manager or another approved secure store; extension access model.
- **Risks:** losing login state, exposing secrets during migration, breaking the
  extension’s content-script contract, or accidentally reintroducing token
  extraction. Do not implement this together with a broad refactor.
- **Suggested verification:** synthetic accounts only; assert secrets never appear
  in application metadata/logs/errors; test restart, migration failure, removal,
  and legacy compatibility in a disposable copy.

### 5. Improve import recovery and metadata observability

- **Objective:** Make TXT bulk import validate all rows before mutation and provide
  clear partial-failure/recovery behavior; add safe diagnostics for catalog/profile
  mismatches without dumping secrets.
- **Affected components:** `ProfileManagerApp.bulk_import_profiles`, account
  setup, `ProfileManager` transaction boundaries, tests, and README.
- **Dependencies:** a product decision on rollback versus explicit resumable
  partial import.
- **Risks:** deleting or rolling back a profile that the user has already used;
  account config and browser data need coordinated handling.
- **Suggested verification:** inject failures at every row/stage; assert no
  unintended profile/data deletion and no reused IDs; test restart and recovery.

### 6. Add runtime validation, update/recovery, and packaging

- **Objective:** deliver the portable Windows distribution described in requirements
  while preserving `profiles/`, `config/`, `extensions/`, and logs across runtime
  updates and failures.
- **Affected components:** new runtime manager/updater, `main()`, packaging files,
  release layout, dependency bundling, and documentation.
- **Dependencies:** chosen Chromium distribution/update source, installer or
  PyInstaller-like tool, version/rollback policy, and secure update handling.
- **Risks:** overwriting browser/profile data, shipping a runtime incompatible with
  existing profiles, or packaging secrets/runtime-local data accidentally.
- **Suggested verification:** clean install, missing runtime, invalid runtime,
  update failure, rollback, existing-profile preservation, and uninstall/update
  tests in disposable copies.

### 7. Establish static checks and then modularize carefully

- **Objective:** add pinned development dependencies and lint/type/syntax checks,
  then split the monolith only after behavior is protected by the current tests.
- **Affected components:** repository tooling plus eventual storage, migration,
  launcher, extension/account, and GUI modules.
- **Dependencies:** preserve test seams/API names and maintain Windows behavior.
- **Risks:** import-time path/logging changes, circular imports, altered monkeypatch
  targets, and regressions in file safety.
- **Suggested verification:** run the existing 170-test suite before/after each
  small extraction, add integration tests for real path resolution, and keep a
  separate refactor change from feature changes.

## 11. Autonomous Agent Notes

- Read `AGENTS.md` and `REQUIREMENTS.md` before making changes. The repository
  prioritizes profile preservation, Windows compatibility, small changes, and
  explicit testing.
- Treat all existing working-tree changes as user-owned. The current pre-existing
  changes are the M8 proxy implementation/test plus the M7 mobile scale-factor
  expectation. Never use `git reset`, `git checkout`, or destructive cleanup to
  make the tree look clean.
- This handoff task intentionally changed no application code. The only intended
  new file is `CODEX_HANDOFF.md`; it should remain unstaged unless the user asks
  for a commit.
- Do not inspect or print raw `config/profiles.json`, `Local State`, profile
  extension configs, logs, or Chromium databases when their contents may contain
  account/session data. Use structural summaries and redaction.
- Use disposable roots under `tmp/` for tests and manual damage scenarios. Never
  delete current `profiles/`, `legacy/data/`, or browser runtime files as part of
  normal development.
- `unittest discover` currently runs tests from an untracked file. If M8 is later
  committed or removed, record the changed test count and status explicitly.
- Test modules load `legacy/profile_manager.py` by reading/compiling it into a
  synthetic module and monkeypatching global paths. Global constants such as
  `DATA_DIR`, `PROFILES_DIR`, `PROFILES_JSON`, `LOCAL_STATE`, `BROWSER_EXE`, and
  `EXT_DIR` are deliberate test seams.
- The actual application writes logs to `legacy/log/`, not top-level `logs/`.
  Logging messages should stay secret-free even when a future error handler adds
  more detail.
- The extension is a content-script autofill mechanism, not an authentication
  service. Do not add token extraction or anti-detection/fingerprint spoofing.
- When changing deletion, migration, metadata, or launch behavior, verify both
  the success path and the preservation path after a simulated failure.
- When reporting results, separate mocked unit-test evidence, real Chromium smoke
  evidence, and manual GUI evidence. Never claim visible GUI or Discord behavior
  is verified merely because the unit suite passes.

## 12. Current Git State

At inspection time:

- **Branch:** `main`
- **Tracking:** `origin/main`; local branch was aligned with the remote tracking
  reference when inspected.
- **HEAD:** `24f7716 M7: add per-profile browser environment presets`
- **Pre-existing modified tracked files:**
  - `legacy/profile_manager.py` — 532 added / 4 removed lines in the working-tree
    M8 proxy changes, plus the mobile DPR default change.
  - `tests/test_m7_environment.py` — one expectation changed from device scale
    factor `2` to `1`.
- **Pre-existing untracked file:** `tests/test_m8_proxy.py` — 33 M8 proxy tests.
- **Expected new file from this task:** `CODEX_HANDOFF.md`, intentionally not
  staged or committed.
- **Recent useful commits:**
  - `24f7716` — M7 browser environment presets
  - `ea05448` — M6 responsive GUI
  - `689fab4` — M5 isolated extension deployment
  - `a7a1c28` — M4 application-owned metadata catalog
  - `ce83066` — M3 managed-profile migration
  - `287464e` — M2 direct Chromium profile lifecycle
  - `44f8da4` — initial project baseline

No commit, reset, discard, branch change, or history rewrite was performed for
this handoff. Test execution only created/retained ignored disposable data under
`tmp/`.
